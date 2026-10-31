-- Original reports and observation JSON remain immutable. The empty legacy
-- discriminator preserves existing row identities; new reports distinguish
-- the same market/time window's independently evaluated price squares.
ALTER TABLE research_observation ADD COLUMN entry_band text NOT NULL DEFAULT '';
ALTER TABLE research_observation DROP CONSTRAINT research_observation_pkey;
ALTER TABLE research_observation ADD PRIMARY KEY(result_id,day,ticker,minute,entry_band);
ALTER TABLE research_observation ADD CONSTRAINT research_entry_band_valid CHECK
    (entry_band='' OR entry_band IN ('50-60','60-70','70-80','80-90','90-100'));
