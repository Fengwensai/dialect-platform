"""数据导出公共服务（后台完善 5）：CSV 下载响应 + 录音 ZIP 打包 + 录音富化。

把散落在 review.py 的 ZIP 打包（storage.read_object 磁盘/COS 透明读字节、缺文件 audio_present=0、
磁盘构建 ZIP + StreamingResponse 1MB 分块）与录音富化收口到这里，review / words / speakers 三个
导出端点共用一份实现，避免拷贝三份。
"""
import csv
import io
import logging
import os
import tempfile
import zipfile
from urllib.parse import quote

from fastapi import Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..models.admin import AdminUser
from ..models.recording import Recording
from ..models.speaker import Speaker
from ..models.task import TaskBatch
from ..models.word import WordLibrary
from ..schemas.review import ReviewRecordingOut
from . import storage

logger = logging.getLogger(__name__)

# 发音人画像码 → manifest 中文显示（值域与 mp.py 的 GENDERS/AGE_BRACKETS 保持一致）
GENDER_LABELS = {"male": "男", "female": "女", "other": "其他"}
AGE_BRACKET_LABELS = {
    "under18": "<18",
    "age18_30": "18-30",
    "age31_45": "31-45",
    "age46_60": "46-60",
    "over60": ">60",
}

EXPORT_COLUMNS = [
    "recording_id",
    "task_id",
    "task_name",
    "status",
    "province_code",
    "word_id",
    "word_code",
    "word_content",
    "word_dialect_point",
    "word_example_sentence",
    "word_pronunciation_hint",
    "word_remark",
    "mandarin_transcript",
    "dialect_transcript",
    "speaker_id",
    "speaker_nickname",
    "speaker_device",
    "speaker_gender",
    "speaker_age_bracket",
    "audio_file",
    "audio_present",
    "audio_duration_ms",
    "file_size",
    "recorded_at",
    "reviewed_at",
]


def enrich_recording(rec: Recording, db: Session) -> ReviewRecordingOut:
    """把一条录音富化成带展示字段的 out（list、verdict 与导出共用）。"""
    task = db.get(TaskBatch, rec.task_id)
    word = db.get(WordLibrary, rec.word_id)
    speaker = db.get(Speaker, rec.speaker_id)
    reviewer = db.get(AdminUser, rec.reviewed_by) if rec.reviewed_by else None
    return ReviewRecordingOut(
        id=rec.id,
        task_id=rec.task_id,
        task_name=task.name if task else f"任务#{rec.task_id}",
        province_code=task.province_code if task else None,
        word_id=rec.word_id,
        word_code=word.code if word else None,
        word_content=word.content if word else f"词条#{rec.word_id}",
        word_dialect_point=word.dialect_point if word else None,
        word_example_sentence=word.example_sentence if word else None,
        word_pronunciation_hint=word.pronunciation_hint if word else None,
        word_remark=word.remark if word else None,
        speaker_id=rec.speaker_id,
        speaker_nickname=speaker.nickname if speaker else None,
        speaker_device=speaker.device_id if speaker else None,
        speaker_gender=speaker.gender if speaker else None,
        speaker_age_bracket=speaker.age_bracket if speaker else None,
        audio_url=storage.play_url(rec.audio_url),  # COS→预签名；本地→相对路径
        audio_duration=rec.audio_duration,
        file_size=rec.file_size,
        quality_status=rec.quality_status,
        quality_flags=rec.quality_flags,
        quality_metrics=rec.quality_metrics,
        mandarin_transcript=rec.mandarin_transcript,
        dialect_transcript=rec.dialect_transcript,
        status=rec.status,
        review_note=rec.review_note,
        reject_reasons=rec.reject_reasons,
        reviewed_by=rec.reviewed_by,
        reviewed_by_name=reviewer.name if reviewer else None,
        created_at=rec.created_at,
        reviewed_at=rec.reviewed_at,
    )


def csv_response(rows: list[dict], columns: list[str], fname: str) -> Response:
    """utf-8-sig CSV 下载响应（Excel 双击可直接打开中文）。"""
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=text.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"; filename*=UTF-8\'\'{quote(fname)}'
        },
    )


def recordings_zip_response(
    db: Session,
    recs: list[Recording],
    arcname_fn,
    zip_filename: str,
) -> StreamingResponse:
    """把一批录音打包成 ZIP = audios/（音频原文件）+ manifest.csv（EXPORT_COLUMNS 全列，utf-8-sig）。

    arcname_fn(rec, out) -> str：决定每条录音在 zip 内的路径（如 audios/{省}/word_{word_id}/{文件名}）。
    大文件友好：逐条落盘暂存 → 磁盘上构建 ZIP（deflate 分块读盘）→ StreamingResponse 1MB 分块流式返回，
    内存峰值 ≈ 单条录音大小。缺文件（storage.read_object 返回 None）不抛错，manifest 标 audio_present=0。
    """
    rows = []
    staged = []  # (临时文件路径, zip 内路径)
    used_names: set[str] = set()  # zip 内路径去重（同名音频加后缀，避免 zipfile Duplicate name 告警）
    tmp = tempfile.TemporaryDirectory()
    try:
        for rec in recs:
            out = enrich_recording(rec, db)
            zip_name = arcname_fn(rec, out)
            base, ext = os.path.splitext(zip_name)
            n = 1
            while zip_name in used_names:
                zip_name = f"{base}_{n}{ext}"
                n += 1
            used_names.add(zip_name)
            content = storage.read_object(rec.audio_url)  # COS/本地统一读字节（单条进内存）
            present = content is not None
            if present:
                tmp_file = os.path.join(tmp.name, f"rec_{rec.id}.bin")
                with open(tmp_file, "wb") as f:
                    f.write(content)
                staged.append((tmp_file, zip_name))
            else:
                logger.warning("export: audio missing for recording %s (%s)", rec.id, rec.audio_url)
            rows.append(
                {
                    "recording_id": rec.id,
                    "task_id": rec.task_id,
                    "task_name": out.task_name,
                    "status": rec.status,
                    "province_code": out.province_code,
                    "word_id": rec.word_id,
                    "word_code": out.word_code,
                    "word_content": out.word_content,
                    "word_dialect_point": out.word_dialect_point or "",
                    "word_example_sentence": out.word_example_sentence or "",
                    "word_pronunciation_hint": out.word_pronunciation_hint or "",
                    "word_remark": out.word_remark or "",
                    "mandarin_transcript": out.mandarin_transcript or "",
                    "dialect_transcript": out.dialect_transcript or "",
                    "speaker_id": rec.speaker_id,
                    "speaker_nickname": out.speaker_nickname,
                    "speaker_device": out.speaker_device,
                    "speaker_gender": GENDER_LABELS.get(out.speaker_gender, out.speaker_gender or ""),
                    "speaker_age_bracket": AGE_BRACKET_LABELS.get(
                        out.speaker_age_bracket, out.speaker_age_bracket or ""
                    ),
                    "audio_file": zip_name if present else "",
                    "audio_present": 1 if present else 0,
                    "audio_duration_ms": rec.audio_duration,
                    "file_size": len(content) if present else rec.file_size,
                    "recorded_at": rec.created_at.isoformat() if rec.created_at else "",
                    "reviewed_at": rec.reviewed_at.isoformat() if rec.reviewed_at else "",
                }
            )

        text = io.StringIO(newline="")
        writer = csv.DictWriter(text, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

        # 磁盘构建 ZIP：zf.write 分块读暂存文件压缩，ZIP 不整包驻内存
        zip_path = os.path.join(tmp.name, "export.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for tmp_file, arcname in staged:
                zf.write(tmp_file, arcname)
            zf.writestr("manifest.csv", text.getvalue().encode("utf-8-sig"))

        def gen():
            try:
                with open(zip_path, "rb") as f:
                    while True:
                        chunk = f.read(1 << 20)  # 1MB 分块
                        if not chunk:
                            break
                        yield chunk
            finally:
                tmp.cleanup()  # 正常流完或客户端断开（GeneratorExit）都清理临时目录

        return StreamingResponse(
            gen(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{zip_filename}"; filename*=UTF-8\'\'{quote(zip_filename)}'
            },
        )
    except Exception:
        tmp.cleanup()
        raise
