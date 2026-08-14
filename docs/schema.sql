-- 方言采集平台 · 数据库表结构（PostgreSQL 方言）
-- 由 scripts/export_schema.py 反射生成，共 12 张表
-- 仅结构，不含数据。表间为逻辑引用（未声明 FOREIGN KEY），详见 docs/database.md。


CREATE TABLE admin_users (
	id SERIAL NOT NULL, 
	username VARCHAR(64) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	name VARCHAR(64) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	province_code VARCHAR(16), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT admin_users_pkey PRIMARY KEY (id)
)

;
CREATE INDEX ix_admin_users_role ON admin_users (role);
CREATE UNIQUE INDEX ix_admin_users_username ON admin_users (username);


CREATE TABLE agreements (
	id SERIAL NOT NULL, 
	type VARCHAR(32) NOT NULL, 
	title VARCHAR(128) NOT NULL, 
	version INTEGER NOT NULL, 
	content TEXT NOT NULL, 
	updated_by INTEGER, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT agreements_pkey PRIMARY KEY (id)
)

;
CREATE INDEX ix_agreements_type ON agreements (type);
CREATE UNIQUE INDEX uq_agreements_type_version ON agreements (type, version);


CREATE TABLE excel_import_logs (
	id SERIAL NOT NULL, 
	filename VARCHAR NOT NULL, 
	total_rows INTEGER NOT NULL, 
	success_count INTEGER NOT NULL, 
	fail_count INTEGER NOT NULL, 
	errors JSON NOT NULL, 
	admin_id INTEGER, 
	imported_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT excel_import_logs_pkey PRIMARY KEY (id)
)

;


CREATE TABLE recordings (
	id SERIAL NOT NULL, 
	task_id INTEGER NOT NULL, 
	word_id INTEGER NOT NULL, 
	speaker_id INTEGER NOT NULL, 
	audio_url VARCHAR(255) NOT NULL, 
	audio_duration INTEGER NOT NULL, 
	file_size INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	review_note VARCHAR(500), 
	reviewed_by INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	reviewed_at TIMESTAMP WITH TIME ZONE, 
	mandarin_transcript VARCHAR(1000), 
	dialect_transcript VARCHAR(1000), 
	content_check_status VARCHAR(20), 
	media_check_trace_id VARCHAR(64), 
	CONSTRAINT recordings_pkey PRIMARY KEY (id)
)

;
CREATE INDEX ix_recordings_speaker_id ON recordings (speaker_id);
CREATE INDEX ix_recordings_status ON recordings (status);
CREATE INDEX ix_recordings_task_id ON recordings (task_id);
CREATE INDEX ix_recordings_word_id ON recordings (word_id);


CREATE TABLE regions (
	code VARCHAR(16) NOT NULL, 
	name VARCHAR(64) NOT NULL, 
	level INTEGER NOT NULL, 
	parent_code VARCHAR(16), 
	CONSTRAINT regions_pkey PRIMARY KEY (code)
)

;
CREATE INDEX ix_regions_name ON regions (name);
CREATE INDEX ix_regions_parent_code ON regions (parent_code);


CREATE TABLE speaker_agreements (
	id SERIAL NOT NULL, 
	speaker_id INTEGER NOT NULL, 
	type VARCHAR(32) NOT NULL, 
	version INTEGER NOT NULL, 
	accepted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT speaker_agreements_pkey PRIMARY KEY (id)
)

;
CREATE INDEX ix_speaker_agreements_speaker_id ON speaker_agreements (speaker_id);
CREATE UNIQUE INDEX uq_speaker_agreements_speaker_type ON speaker_agreements (speaker_id, type);


CREATE TABLE speakers (
	id SERIAL NOT NULL, 
	device_id VARCHAR(64), 
	openid VARCHAR(64), 
	nickname VARCHAR(64) NOT NULL, 
	avatar_url VARCHAR(255), 
	province_code VARCHAR(16), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	gender VARCHAR(10), 
	age_bracket VARCHAR(20), 
	city_code VARCHAR(16), 
	team_code VARCHAR(32), 
	CONSTRAINT speakers_pkey PRIMARY KEY (id)
)

;
CREATE INDEX ix_speakers_city_code ON speakers (city_code);
CREATE UNIQUE INDEX ix_speakers_device_id ON speakers (device_id);
CREATE UNIQUE INDEX ix_speakers_openid ON speakers (openid);
CREATE INDEX ix_speakers_province_code ON speakers (province_code);
CREATE INDEX ix_speakers_team_code ON speakers (team_code);


CREATE TABLE task_batch_items (
	id SERIAL NOT NULL, 
	task_batch_id INTEGER NOT NULL, 
	word_id INTEGER NOT NULL, 
	CONSTRAINT task_batch_items_pkey PRIMARY KEY (id)
)

;
CREATE INDEX ix_task_batch_items_task_batch_id ON task_batch_items (task_batch_id);
CREATE INDEX ix_task_batch_items_word_id ON task_batch_items (word_id);
CREATE UNIQUE INDEX uq_task_batch_items_batch_word ON task_batch_items (task_batch_id, word_id);


CREATE TABLE task_batches (
	id SERIAL NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	description VARCHAR(500), 
	province_code VARCHAR(16) NOT NULL, 
	city_code VARCHAR(16), 
	district_code VARCHAR(16), 
	required_audio_count INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_by INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	published_at TIMESTAMP WITH TIME ZONE, 
	team_code VARCHAR(32), 
	is_demo BOOLEAN DEFAULT false, 
	claim_limit INTEGER DEFAULT 10 NOT NULL, 
	CONSTRAINT task_batches_pkey PRIMARY KEY (id)
)

;
CREATE INDEX ix_task_batches_city_code ON task_batches (city_code);
CREATE INDEX ix_task_batches_district_code ON task_batches (district_code);
CREATE INDEX ix_task_batches_province_code ON task_batches (province_code);
CREATE INDEX ix_task_batches_status ON task_batches (status);
CREATE INDEX ix_task_batches_team_code ON task_batches (team_code);


CREATE TABLE task_claims (
	id SERIAL NOT NULL, 
	task_id INTEGER NOT NULL, 
	word_id INTEGER NOT NULL, 
	speaker_id INTEGER NOT NULL, 
	claimed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT task_claims_pkey PRIMARY KEY (id)
)

;
CREATE INDEX ix_task_claims_speaker_id ON task_claims (speaker_id);
CREATE INDEX ix_task_claims_task_id ON task_claims (task_id);
CREATE INDEX ix_task_claims_task_speaker ON task_claims (task_id, speaker_id);
CREATE INDEX ix_task_claims_word_id ON task_claims (word_id);
CREATE UNIQUE INDEX uq_task_claims_task_word ON task_claims (task_id, word_id);


CREATE TABLE team_codes (
	id SERIAL NOT NULL, 
	code VARCHAR(32) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	province_code VARCHAR(16) NOT NULL, 
	city_code VARCHAR(16) NOT NULL, 
	created_by INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	CONSTRAINT team_codes_pkey PRIMARY KEY (id), 
	CONSTRAINT team_codes_code_key UNIQUE NULLS DISTINCT (code), 
	CONSTRAINT uq_team_code_region UNIQUE NULLS DISTINCT (province_code, city_code)
)

;
CREATE INDEX ix_team_codes_city_code ON team_codes (city_code);
CREATE INDEX ix_team_codes_province_code ON team_codes (province_code);


CREATE TABLE word_library (
	id SERIAL NOT NULL, 
	code VARCHAR(64) NOT NULL, 
	dialect_point VARCHAR(128) NOT NULL, 
	content VARCHAR(255) NOT NULL, 
	example_sentence VARCHAR(500), 
	remark VARCHAR(500), 
	pronunciation_hint VARCHAR(500), 
	province_code VARCHAR(16), 
	city_code VARCHAR(16), 
	district_code VARCHAR(16), 
	created_by INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	status VARCHAR(20) DEFAULT 'active'::character varying NOT NULL, 
	CONSTRAINT word_library_pkey PRIMARY KEY (id)
)

;
CREATE INDEX ix_word_library_city_code ON word_library (city_code);
CREATE INDEX ix_word_library_code ON word_library (code);
CREATE INDEX ix_word_library_content ON word_library (content);
CREATE INDEX ix_word_library_dialect_point ON word_library (dialect_point);
CREATE INDEX ix_word_library_district_code ON word_library (district_code);
CREATE INDEX ix_word_library_province_code ON word_library (province_code);
CREATE INDEX ix_word_library_status ON word_library (status);
