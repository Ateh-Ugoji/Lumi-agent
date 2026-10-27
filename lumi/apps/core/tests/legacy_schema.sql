CREATE TABLE chat_messages (
	id INTEGER NOT NULL, 
	profile_id INTEGER NOT NULL, 
	role VARCHAR(9) NOT NULL, 
	content VARCHAR NOT NULL, 
	tool_calls JSON, 
	tool_name VARCHAR, 
	tools_used JSON, 
	reason VARCHAR, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(profile_id) REFERENCES profiles (id)
);
CREATE TABLE listening_matches (
	id INTEGER NOT NULL, 
	profile_id INTEGER NOT NULL, 
	platform VARCHAR NOT NULL, 
	platform_post_id VARCHAR NOT NULL, 
	author_handle VARCHAR NOT NULL, 
	caption VARCHAR NOT NULL, 
	platform_url VARCHAR NOT NULL, 
	metrics JSON, 
	discovered_at DATETIME NOT NULL, 
	alerted_at DATETIME, 
	alert_dismissed BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_listening_matches_profile_id_platform_post_id UNIQUE (profile_id, platform_post_id), 
	FOREIGN KEY(profile_id) REFERENCES profiles (id)
);
CREATE TABLE mcp_auth_accounts (
	id INTEGER NOT NULL, 
	account VARCHAR NOT NULL, 
	access_token VARCHAR NOT NULL, 
	refresh_token VARCHAR, 
	token_type VARCHAR NOT NULL, 
	scopes VARCHAR, 
	expires_at DATETIME, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE metric_snapshots (
	id INTEGER NOT NULL, 
	post_id INTEGER NOT NULL, 
	age_hours FLOAT, 
	source VARCHAR, 
	captured_at DATETIME NOT NULL, 
	likes INTEGER, 
	comments INTEGER, 
	shares INTEGER, 
	views INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_metric_snapshots_post_id_captured_at UNIQUE (post_id, captured_at), 
	FOREIGN KEY(post_id) REFERENCES posts (id)
);
CREATE TABLE niche_framework_reports (
	id INTEGER NOT NULL, 
	profile_id INTEGER NOT NULL, 
	niche VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	payload JSON, 
	posts_analyzed INTEGER NOT NULL, 
	winner_count INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(profile_id) REFERENCES profiles (id)
);
CREATE TABLE own_post_analysis (
	id INTEGER NOT NULL, 
	post_id INTEGER NOT NULL, 
	prompt_version VARCHAR, 
	analysis JSON, 
	status VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(post_id) REFERENCES posts (id)
);
CREATE TABLE peer_frameworks (
	id INTEGER NOT NULL, 
	profile_id INTEGER NOT NULL, 
	"query" VARCHAR NOT NULL, 
	niche_title VARCHAR NOT NULL, 
	payload JSON, 
	analyzed_peers_count INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(profile_id) REFERENCES profiles (id)
);
CREATE TABLE poll_config (
	id INTEGER NOT NULL, 
	profile_id INTEGER NOT NULL, 
	interval_minutes INTEGER NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	last_polled_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(profile_id) REFERENCES profiles (id)
);
CREATE TABLE post_taggings (
	id INTEGER NOT NULL, 
	post_id VARCHAR NOT NULL, 
	handle VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	analysis JSON, 
	framework_guess VARCHAR, 
	validation_error VARCHAR, 
	prompt_version VARCHAR NOT NULL, 
	tagged_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_post_taggings_post_id_prompt_version UNIQUE (post_id, prompt_version)
);
CREATE TABLE posts (
	id INTEGER NOT NULL, 
	profile_id INTEGER NOT NULL, 
	platform_post_id VARCHAR NOT NULL, 
	caption VARCHAR NOT NULL, 
	published_at DATETIME NOT NULL, 
	alerted_at DATETIME, 
	alert_dismissed BOOLEAN NOT NULL, 
	source VARCHAR, 
	last_seen_at DATETIME, 
	is_deleted_suspect BOOLEAN NOT NULL, 
	text_truncated BOOLEAN NOT NULL, 
	kind VARCHAR, 
	kind_source VARCHAR, 
	conversation_id VARCHAR, 
	thread_position INTEGER, 
	is_thread_head BOOLEAN, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_posts_profile_id_platform_post_id UNIQUE (profile_id, platform_post_id), 
	FOREIGN KEY(profile_id) REFERENCES profiles (id)
);
CREATE TABLE profile_baseline (
	id INTEGER NOT NULL, 
	profile_id INTEGER NOT NULL, 
	window_days INTEGER NOT NULL, 
	n_posts INTEGER NOT NULL, 
	median_views FLOAT NOT NULL, 
	median_engagement FLOAT NOT NULL, 
	p75_views FLOAT NOT NULL, 
	baseline_reliable BOOLEAN NOT NULL, 
	computed_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(profile_id) REFERENCES profiles (id)
);
CREATE TABLE profile_snapshots (
	id INTEGER NOT NULL, 
	profile_id INTEGER NOT NULL, 
	captured_at DATETIME NOT NULL, 
	followers INTEGER, 
	following INTEGER, 
	source VARCHAR, 
	PRIMARY KEY (id), 
	FOREIGN KEY(profile_id) REFERENCES profiles (id)
);
CREATE TABLE profiles (
	id INTEGER NOT NULL, 
	name VARCHAR NOT NULL, 
	platform VARCHAR NOT NULL, 
	handle VARCHAR NOT NULL, 
	pfm_account_id VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	timezone VARCHAR, 
	timezone_source VARCHAR, 
	PRIMARY KEY (id), 
	UNIQUE (pfm_account_id)
);
CREATE TABLE repurpose_attempts (
	id INTEGER NOT NULL, 
	request_id INTEGER NOT NULL, 
	platform VARCHAR NOT NULL, 
	tier VARCHAR, 
	model VARCHAR, 
	provider VARCHAR, 
	attempt_no INTEGER NOT NULL, 
	output VARCHAR NOT NULL, 
	must_keep_passed BOOLEAN NOT NULL, 
	judge_verdict VARCHAR, 
	judge_confidence FLOAT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(request_id) REFERENCES repurpose_requests (id)
);
CREATE TABLE repurpose_requests (
	id INTEGER NOT NULL, 
	profile_id INTEGER NOT NULL, 
	source_caption VARCHAR NOT NULL, 
	route_label VARCHAR, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(profile_id) REFERENCES profiles (id)
);
CREATE TABLE style_answers (
	id INTEGER NOT NULL, 
	profile_id INTEGER NOT NULL, 
	question_key VARCHAR NOT NULL, 
	answer VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(profile_id) REFERENCES profiles (id)
);
CREATE TABLE turn_classifications (
	id INTEGER NOT NULL, 
	profile_id INTEGER NOT NULL, 
	message_id INTEGER, 
	created_at DATETIME NOT NULL, 
	message_text_hash VARCHAR NOT NULL, 
	message_preview VARCHAR NOT NULL, 
	rule_class VARCHAR NOT NULL, 
	rule_matched VARCHAR, 
	jev_called BOOLEAN NOT NULL, 
	jev_class VARCHAR, 
	jev_probs JSON, 
	jev_confidence FLOAT, 
	jev_latency_ms INTEGER, 
	jev_error VARCHAR, 
	final_class VARCHAR NOT NULL, 
	path_taken VARCHAR NOT NULL, 
	tools_called JSON, 
	credits_spent FLOAT, 
	total_latency_ms INTEGER, 
	user_corrected BOOLEAN, 
	timings JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(profile_id) REFERENCES profiles (id), 
	FOREIGN KEY(message_id) REFERENCES chat_messages (id)
);
CREATE TABLE user_actions (
	id INTEGER NOT NULL, 
	attempt_id INTEGER NOT NULL, 
	action VARCHAR(6) NOT NULL, 
	edited_text VARCHAR, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(attempt_id) REFERENCES repurpose_attempts (id)
);
CREATE TABLE user_activity (
	id INTEGER NOT NULL, 
	profile_id INTEGER NOT NULL, 
	platform VARCHAR NOT NULL, 
	platform_post_id VARCHAR NOT NULL, 
	kind VARCHAR NOT NULL, 
	caption VARCHAR NOT NULL, 
	published_at DATETIME NOT NULL, 
	likes INTEGER, 
	replies INTEGER, 
	views INTEGER, 
	source VARCHAR, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_user_activity_profile_id_platform_post_id UNIQUE (profile_id, platform_post_id), 
	FOREIGN KEY(profile_id) REFERENCES profiles (id)
);
CREATE TABLE user_search_requests (
	id INTEGER NOT NULL, 
	profile_id INTEGER NOT NULL, 
	handle VARCHAR NOT NULL, 
	request_note VARCHAR, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(profile_id) REFERENCES profiles (id)
);
CREATE TABLE voice_profiles (
	id INTEGER NOT NULL, 
	profile_id INTEGER NOT NULL, 
	version INTEGER NOT NULL, 
	is_current BOOLEAN NOT NULL, 
	payload JSON, 
	example_post_ids JSON, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_voice_profiles_profile_id_version UNIQUE (profile_id, version), 
	FOREIGN KEY(profile_id) REFERENCES profiles (id)
);
CREATE UNIQUE INDEX ix_mcp_auth_accounts_account ON mcp_auth_accounts (account);
CREATE UNIQUE INDEX ix_poll_config_profile_id ON poll_config (profile_id);
CREATE UNIQUE INDEX uq_voice_profiles_current_per_profile ON voice_profiles (profile_id) WHERE is_current = 1;
CREATE INDEX ix_chat_messages_profile_id ON chat_messages (profile_id);
CREATE INDEX ix_listening_matches_profile_id ON listening_matches (profile_id);
CREATE INDEX ix_metric_snapshots_post_id ON metric_snapshots (post_id);
CREATE INDEX ix_metric_snapshots_post_id_captured_at_desc ON metric_snapshots (post_id, captured_at DESC);
CREATE INDEX ix_niche_framework_reports_profile_id ON niche_framework_reports (profile_id);
CREATE INDEX ix_own_post_analysis_post_id ON own_post_analysis (post_id);
CREATE INDEX ix_own_post_analysis_post_id_prompt_version ON own_post_analysis (post_id, prompt_version);
CREATE INDEX ix_peer_frameworks_profile_id ON peer_frameworks (profile_id);
CREATE INDEX ix_post_taggings_post_id ON post_taggings (post_id);
CREATE INDEX ix_posts_profile_id ON posts (profile_id);
CREATE INDEX ix_profile_baseline_profile_id ON profile_baseline (profile_id);
CREATE INDEX ix_profile_snapshots_profile_id ON profile_snapshots (profile_id);
CREATE INDEX ix_repurpose_attempts_request_id ON repurpose_attempts (request_id);
CREATE INDEX ix_repurpose_requests_profile_id ON repurpose_requests (profile_id);
CREATE INDEX ix_style_answers_profile_id ON style_answers (profile_id);
CREATE INDEX ix_turn_classifications_created_at ON turn_classifications (created_at);
CREATE INDEX ix_turn_classifications_profile_id ON turn_classifications (profile_id);
CREATE INDEX ix_user_actions_attempt_id ON user_actions (attempt_id);
CREATE INDEX ix_user_activity_profile_id ON user_activity (profile_id);
CREATE INDEX ix_user_search_requests_profile_id ON user_search_requests (profile_id);
CREATE INDEX ix_voice_profiles_profile_id ON voice_profiles (profile_id);
