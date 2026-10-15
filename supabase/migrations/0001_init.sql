-- Local sqlite is the demo store. These policies are the Postgres contract.
-- A test fails if a table is missing ENABLE ROW LEVEL SECURITY or a policy.

CREATE TABLE profiles (id uuid PRIMARY KEY, user_id uuid NOT NULL);
CREATE TABLE paper_accounts (id uuid PRIMARY KEY, user_id uuid NOT NULL);
CREATE TABLE strategies (id uuid PRIMARY KEY, user_id uuid NOT NULL, dsl jsonb NOT NULL);
CREATE TABLE backtests (id uuid PRIMARY KEY, user_id uuid NOT NULL, status text NOT NULL);
CREATE TABLE paper_orders (id uuid PRIMARY KEY, user_id uuid NOT NULL);
CREATE TABLE paper_positions (id uuid PRIMARY KEY, user_id uuid NOT NULL);
CREATE TABLE deployments (id uuid PRIMARY KEY, user_id uuid NOT NULL);
CREATE TABLE agent_runs (id uuid PRIMARY KEY, user_id uuid NOT NULL);
CREATE TABLE agent_messages (id uuid PRIMARY KEY, user_id uuid NOT NULL);
CREATE TABLE jobs (id uuid PRIMARY KEY, user_id uuid NOT NULL, status text NOT NULL);
CREATE TABLE user_secrets (id uuid PRIMARY KEY, user_id uuid NOT NULL, ciphertext bytea NOT NULL);
CREATE TABLE broker_links (id uuid PRIMARY KEY, user_id uuid NOT NULL);
CREATE TABLE broker_snapshots (id uuid PRIMARY KEY, user_id uuid NOT NULL);
CREATE TABLE audit_log (id uuid PRIMARY KEY, user_id uuid NOT NULL);

ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE strategies ENABLE ROW LEVEL SECURITY;
ALTER TABLE backtests ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE deployments ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_secrets ENABLE ROW LEVEL SECURITY;
ALTER TABLE broker_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE broker_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY profiles_owner ON profiles FOR ALL USING (user_id = auth.uid());
CREATE POLICY paper_accounts_owner ON paper_accounts FOR ALL USING (user_id = auth.uid());
CREATE POLICY strategies_owner ON strategies FOR ALL USING (user_id = auth.uid());
CREATE POLICY backtests_owner ON backtests FOR ALL USING (user_id = auth.uid());
CREATE POLICY paper_orders_owner ON paper_orders FOR ALL USING (user_id = auth.uid());
CREATE POLICY paper_positions_owner ON paper_positions FOR ALL USING (user_id = auth.uid());
CREATE POLICY deployments_owner ON deployments FOR ALL USING (user_id = auth.uid());
CREATE POLICY agent_runs_owner ON agent_runs FOR ALL USING (user_id = auth.uid());
CREATE POLICY agent_messages_owner ON agent_messages FOR ALL USING (user_id = auth.uid());
CREATE POLICY jobs_owner ON jobs FOR ALL USING (user_id = auth.uid());
CREATE POLICY broker_links_owner ON broker_links FOR ALL USING (user_id = auth.uid());
CREATE POLICY broker_snapshots_owner ON broker_snapshots FOR ALL USING (user_id = auth.uid());
CREATE POLICY audit_log_owner ON audit_log FOR ALL USING (user_id = auth.uid());
-- user_secrets has RLS enabled and no policy for the authenticated role.
-- Only the service role, through packages/secrets, reads the ciphertext.
