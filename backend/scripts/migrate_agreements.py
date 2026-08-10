"""协议表迁移（阶段九）：agreements + speaker_agreements 建表并种子三份协议 v1。

- agreements：协议版本表，每行 = 某协议的一个不可变版本（UNIQUE(type, version)）。
- speaker_agreements：发音人接受记录，每人每类记录已接受版本（UNIQUE(speaker_id, type)）。
幂等：CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS / 种子 INSERT ... WHERE NOT EXISTS。
中文正文走绑定参数，避免 Git Bash 控制台 GBK 编码问题。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text

from app.db import engine

USER_AGREEMENT = """《方言采集平台用户协议》

更新日期：见协议版本号

欢迎使用方言采集平台（以下简称"本平台"）。在登录并使用本平台前，请您仔细阅读并充分理解本协议全部内容，特别是加粗显示的条款。您勾选同意本协议即视为已阅读并同意受本协议约束。

一、服务说明
本平台是一款面向方言研究的语音采集平台，通过微信小程序向注册用户（发音人）下发方言词条任务，用户按要求录制方言语音并提交，用于方言研究与语言资源保护。

二、账号注册与安全
1. 您通过微信授权登录本平台，我们依据微信授权信息（openid）及设备标识识别您的账号。您应妥善保管您的微信账号，因您自身保管不善造成的损失由您自行承担。
2. 您承诺所填写的昵称、头像、性别、年龄段等个人信息真实、合法，不得冒用他人身份。

三、用户行为规范
1. 您应本人完成语音录制，保证录音内容为本人真实发音，不得使用他人声音、合成声音或非本次任务要求的语言内容。
2. 您不得利用本平台录制、上传任何违反法律法规、违背公序良俗或侵犯第三方权益的内容。
3. 您不得以任何方式绕过本平台的身份识别、属地隔离、协议确认等安全机制。

四、声音授权
您为完成采集任务所录制的语音，其授权使用范围详见《声音单独授权协议》。未签署该协议的录音视为无效采集。

五、服务变更与中断
本平台可能因维护、升级、系统故障等原因暂停或调整服务，将尽合理努力提前通知。因不可抗力导致的损失，本平台不承担责任。

六、知识产权
1. 本平台软件、界面、文档及相关技术的知识产权归平台所有。
2. 您的语音及衍生转写内容的知识产权归属及使用规则，以《声音单独授权协议》为准。

七、协议变更
我们可能根据法律法规或业务需要修订本协议。协议更新即生成新版本，您在下次登录时需重新阅读并同意最新版本后方可继续使用本平台。

八、法律适用与争议解决
本协议的订立、履行与解释适用中华人民共和国法律。因本协议产生的争议，双方应友好协商解决；协商不成的，提交平台运营方所在地有管辖权的人民法院解决。

九、联系我们
如您对本协议有任何疑问，可通过平台「我的」页面反馈渠道与我们联系。"""

PRIVACY_POLICY = """《方言采集平台隐私政策》

更新日期：见协议版本号

本平台重视您的个人信息保护。本政策说明我们如何收集、使用、存储和保护您的个人信息，以及您享有的权利。勾选同意即视为您已阅读并同意本政策。

一、我们收集的信息
1. 账号信息：微信登录授权返回的 openid、设备标识（device_id）。
2. 个人资料：您主动填写的昵称、头像、性别、年龄段。
3. 属地信息：您绑定团队码后确认的省、市属地及团队码。
4. 采集内容：您录制的方言语音、词条编码、语音对应的转写文本（如审核环节生成）、录音时长与状态。
5. 使用记录：任务领取记录、录音提交与审核记录、数据导出记录。

二、信息的使用目的
1. 用于登录鉴权、身份识别与账号管理。
2. 用于任务匹配与分发（按属地、年龄段等合理分发采集任务）。
3. 用于方言研究：对语音进行分析、转写、标注，并纳入研究数据集。
4. 用于平台运营与安全：审核录音质量、排查异常行为、保障系统安全。

三、信息的存储与保护
1. 您的个人信息存储于受访问控制的服务器，采取加密传输、权限隔离等措施防止未授权访问。
2. 我们将根据采集项目的需要保留个人信息，并在不再需要时予以删除或匿名化处理。

四、信息的共享与对外提供
1. 您的语音、转写文本及画像信息可能以去标识化或匿名化的形式纳入数据集，提供给方言研究机构、学术团队用于语言资源保护与研究，用于学术论文、公开语料库等场景。
2. 除上述用途、法律法规要求或司法机关依法调取外，我们不会向任何第三方披露您的个人信息。

五、未成年人保护
本平台采集任务原则上面向成年人。若您为未成年人，须在监护人同意并陪同下使用本平台，监护人需同时同意本政策及《声音单独授权协议》。

六、您的权利
1. 您有权查询、更正您的个人资料（头像、昵称、性别、年龄段等）。
2. 您有权要求删除您的账号及相关个人信息。删除账号后，您将无法继续使用本平台。
3. 您有权撤回对声音采集的授权，具体规则见《声音单独授权协议》。

七、政策变更
本政策更新将生成新版本，您在下次登录时需重新阅读并同意后方可继续使用。

八、联系我们
如您对本政策有任何疑问，可通过平台「我的」页面反馈渠道与我们联系。"""

VOICE_AUTH = """《声音单独授权协议》

更新日期：见协议版本号

您在本平台录制的声音及其衍生数据，涉及个人生物识别信息与语音特征，本协议就声音的授权使用单独作出约定。请仔细阅读，勾选同意即视为您已充分理解并同意以下条款。

一、授权内容
您授权本平台使用您在本平台采集任务中录制的全部方言语音，以及与语音相关的转写文本、标注信息和基础画像信息（不含可直接识别您个人身份的真实姓名、手机号等）。

二、授权用途
1. 平台内部存储、处理、审核与标注。
2. 用于方言学、语言学、语言资源保护等学术研究、分析与统计。
3. 以去标识化或匿名化方式纳入研究数据集，供合作研究机构使用。
4. 用于学术论文、公开语料库、科研展示等公开发布场景（仅限去标识化或匿名化形式）。

三、授权性质与期限
1. 本授权为不可撤销的授权，自您同意之日起长期有效，直至您依法撤回。
2. 您的撤回申请可通过平台「我的」页面提交。自撤回之日起，本平台不再就新增录音使用您的语音；但已进入数据集或已对外提供的语音数据，因技术原因可能无法追溯删除，您同意该部分数据可继续用于研究用途。

四、权利声明与保证
1. 您保证所录制语音为本人真实声音，不侵犯任何第三方权利。
2. 您知晓声音具有可识别的个人特征，尽管我们采取去标识化处理，仍不能排除被识别的可能性，您同意自行承担由此产生的合理风险。

五、无报酬说明
本平台为公益性质的方言资源采集项目，语音采集为志愿参与，您同意不因授权使用您的语音而要求任何形式的报酬或补偿。

六、未成年人
若您为未成年人，须由监护人同意本协议后方可参与录制，监护人应对被监护人语音的授权使用承担相应责任。

七、联系我们
如您对本授权协议有任何疑问，可通过平台「我的」页面反馈渠道与我们联系。"""


def main():
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS agreements ("
                " id SERIAL PRIMARY KEY,"
                " type VARCHAR(32) NOT NULL,"
                " title VARCHAR(128) NOT NULL,"
                " version INTEGER NOT NULL,"
                " content TEXT NOT NULL,"
                " updated_by INTEGER,"
                " updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_agreements_type_version "
                "ON agreements (type, version)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_agreements_type ON agreements (type)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS speaker_agreements ("
                " id SERIAL PRIMARY KEY,"
                " speaker_id INTEGER NOT NULL,"
                " type VARCHAR(32) NOT NULL,"
                " version INTEGER NOT NULL,"
                " accepted_at TIMESTAMPTZ NOT NULL DEFAULT now()"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_speaker_agreements_speaker_type "
                "ON speaker_agreements (speaker_id, type)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_speaker_agreements_speaker_id "
                "ON speaker_agreements (speaker_id)"
            )
        )
        # 种子三份协议 v1（仅当该 type 尚不存在）
        for t, title, content in [
            ("user_agreement", "用户协议", USER_AGREEMENT),
            ("privacy_policy", "隐私政策", PRIVACY_POLICY),
            ("voice_auth", "声音单独授权协议", VOICE_AUTH),
        ]:
            conn.execute(
                text(
                    "INSERT INTO agreements (type, title, version, content, updated_by) "
                    "SELECT CAST(:t AS VARCHAR(32)), CAST(:title AS VARCHAR(128)), 1, "
                    "CAST(:content AS TEXT), NULL "
                    "WHERE NOT EXISTS (SELECT 1 FROM agreements WHERE type = CAST(:t AS VARCHAR(32)))"
                ),
                {"t": t, "title": title, "content": content},
            )
    print("migrate_agreements: OK")


if __name__ == "__main__":
    main()
