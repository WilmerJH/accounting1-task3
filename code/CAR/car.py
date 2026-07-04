# Build Y: market-adjusted CAR around 10-K filing dates
# -----------------------------------------------------
# Input:
#   data/generated/tone/full_10k_sample_dedup_stratified_1500_per_year.csv
#   data/external/cik_to_permno.csv.gz
#   data/external/ret_all.csv.gz
#   data/external/index.csv
#
# Output:
#   data/generated/CAR/10k_sample_with_car.csv
#   data/generated/CAR/analysis_sample_car_m1_p1.csv

from pathlib import Path
import duckdb


# ------------------------------------------------------------
# 1. Setup
# ------------------------------------------------------------

print("Step 1: setup paths and DuckDB settings", flush=True)

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[1]

generated_dir = ROOT / "data/generated"
generated_dir.mkdir(parents=True, exist_ok=True)
car_dir = ROOT / "data/generated/CAR"
car_dir.mkdir(parents=True, exist_ok=True)

# Use /tmp for DuckDB temporary files. It usually has more free space in Codespaces.
duckdb_temp = Path("/tmp/duckdb_temp")
duckdb_temp.mkdir(parents=True, exist_ok=True)

con = duckdb.connect()

# Keep memory conservative for Codespaces.
con.execute("SET memory_limit='1GB'")
con.execute("SET threads=1")
con.execute("SET preserve_insertion_order=false")
con.execute(f"SET temp_directory='{duckdb_temp}'")

sample_path = ROOT / "data/generated/tone/full_10k_sample_dedup_stratified_1500_per_year.csv"
ret_path = ROOT / "data/external/ret_all.csv.gz"
index_path = ROOT / "data/external/index.csv"
link_path = ROOT / "data/external/cik_to_permno.csv.gz"

out_path = car_dir / "10k_sample_with_car.csv"
analysis_path = car_dir / "analysis_sample_car_m1_p1.csv"

ret_filtered_parquet = car_dir / "ret_filtered.parquet"

required_files = [sample_path, ret_path, index_path, link_path]
for p in required_files:
    if not p.exists():
        raise FileNotFoundError(f"Missing required file: {p}")

print("Paths OK.", flush=True)


# ------------------------------------------------------------
# 2. Load 10-K sample
# ------------------------------------------------------------

print("Step 2: loading 10-K sample", flush=True)

con.execute(f"""
CREATE OR REPLACE TEMP TABLE sample AS
SELECT
    ROW_NUMBER() OVER () AS row_id,
    *,
    TRY_CAST(cik AS BIGINT) AS cik_num,
    TRY_CAST(filing_date AS DATE) AS filing_dt,
    TRY_CAST(report_date AS DATE) AS report_dt
FROM read_csv_auto(
    '{sample_path}',
    all_varchar = true
)
WHERE filing_date IS NOT NULL
  AND TRY_CAST(filing_date AS DATE) IS NOT NULL
  AND TRY_CAST(filing_date AS DATE) <= DATE '2024-12-31'
""")

print("Step 2 done.", flush=True)


# ------------------------------------------------------------
# 3. Build target CIK list
# ------------------------------------------------------------

print("Step 3: building target CIK list", flush=True)

con.execute("""
CREATE OR REPLACE TEMP TABLE target_ciks AS
SELECT DISTINCT cik_num
FROM sample
WHERE cik_num IS NOT NULL
""")

print("Step 3 done.", flush=True)


# ------------------------------------------------------------
# 4. Build CIK-PERMNO link table
# ------------------------------------------------------------

print("Step 4: building CIK-PERMNO link table", flush=True)

con.execute(f"""
CREATE OR REPLACE TEMP TABLE link AS
SELECT DISTINCT
    TRY_CAST(l.cik AS BIGINT) AS cik_num,
    TRY_CAST(l.LPERMNO AS BIGINT) AS permno,
    TRY_CAST(l.LPERMCO AS BIGINT) AS permco,
    l.GVKEY AS gvkey,
    l.LINKTYPE AS linktype,
    TRY_CAST(l.LINKDT AS DATE) AS linkdt,
    CASE
        WHEN l.LINKENDDT IS NULL OR l.LINKENDDT = '' OR l.LINKENDDT = 'E'
            THEN DATE '9999-12-31'
        ELSE TRY_CAST(l.LINKENDDT AS DATE)
    END AS linkenddt
FROM read_csv_auto(
    '{link_path}',
    all_varchar = true,
    ignore_errors = true
) AS l
INNER JOIN target_ciks AS c
    ON TRY_CAST(l.cik AS BIGINT) = c.cik_num
WHERE TRY_CAST(l.cik AS BIGINT) IS NOT NULL
  AND TRY_CAST(l.LPERMNO AS BIGINT) IS NOT NULL
  AND TRY_CAST(l.LINKDT AS DATE) IS NOT NULL
  AND l.LINKTYPE IN ('LC', 'LU', 'LS')
""")

print("Step 4 done.", flush=True)


# ------------------------------------------------------------
# 5. Match filings to valid PERMNO links
# ------------------------------------------------------------

print("Step 5: matching filings to PERMNO", flush=True)

con.execute("""
CREATE OR REPLACE TEMP TABLE sample_linked AS
SELECT
    s.*,
    l.permno,
    l.permco,
    l.gvkey,
    l.linktype,
    l.linkdt,
    l.linkenddt
FROM sample AS s
LEFT JOIN link AS l
    ON s.cik_num = l.cik_num
   AND s.filing_dt >= l.linkdt
   AND s.filing_dt <= l.linkenddt
""")

print("Step 5 done.", flush=True)


# ------------------------------------------------------------
# 6. Create target PERMNO list and date bounds
# ------------------------------------------------------------

print("Step 6: creating target PERMNO list and date bounds", flush=True)

con.execute("""
CREATE OR REPLACE TEMP TABLE target_permnos AS
SELECT DISTINCT permno
FROM sample_linked
WHERE permno IS NOT NULL
""")

con.execute("""
CREATE OR REPLACE TEMP TABLE date_bounds AS
SELECT
    MIN(filing_dt) - INTERVAL 10 DAY AS min_needed_date,
    MAX(filing_dt) + INTERVAL 10 DAY AS max_needed_date
FROM sample_linked
WHERE filing_dt IS NOT NULL
""")

print("Step 6 done.", flush=True)


# ------------------------------------------------------------
# 7. Filter CRSP daily returns
# ------------------------------------------------------------

print("Step 7: filtering CRSP daily returns. This may take several minutes.", flush=True)

# Write filtered returns to parquet first, instead of keeping the first large scan only in memory.
if ret_filtered_parquet.exists():
    ret_filtered_parquet.unlink()

con.execute(f"""
COPY (
    SELECT
        TRY_CAST(r.PERMNO AS BIGINT) AS permno,
        TRY_CAST(r.date AS DATE) AS ret_date,
        TRY_CAST(r.RET AS DOUBLE) AS ret,
        TRY_CAST(r.RETX AS DOUBLE) AS retx,
        TRY_CAST(r.PRC AS DOUBLE) AS prc,
        TRY_CAST(r.VOL AS DOUBLE) AS vol,
        TRY_CAST(r.SHRCD AS INTEGER) AS shrcd,
        TRY_CAST(r.EXCHCD AS INTEGER) AS exchcd
    FROM read_csv_auto(
        '{ret_path}',
        all_varchar = true
    ) AS r
    INNER JOIN target_permnos AS p
        ON TRY_CAST(r.PERMNO AS BIGINT) = p.permno
    WHERE TRY_CAST(r.date AS DATE) BETWEEN
        (SELECT min_needed_date FROM date_bounds)
        AND
        (SELECT max_needed_date FROM date_bounds)
    AND TRY_CAST(r.RET AS DOUBLE) IS NOT NULL
) TO '{ret_filtered_parquet}' (FORMAT PARQUET)
""")

print("Step 7 done.", flush=True)


# ------------------------------------------------------------
# 8. Load market returns
# ------------------------------------------------------------

print("Step 8: loading market returns", flush=True)

con.execute(f"""
CREATE OR REPLACE TEMP TABLE mkt AS
SELECT
    TRY_CAST(DATE AS DATE) AS ret_date,
    TRY_CAST(vwretd AS DOUBLE) AS vwretd,
    TRY_CAST(ewretd AS DOUBLE) AS ewretd
FROM read_csv_auto(
    '{index_path}',
    all_varchar = true
)
WHERE TRY_CAST(DATE AS DATE) IS NOT NULL
  AND TRY_CAST(vwretd AS DOUBLE) IS NOT NULL
""")

print("Step 8 done.", flush=True)


# ------------------------------------------------------------
# 9. Merge stock returns with market returns
# ------------------------------------------------------------

print("Step 9: merging stock returns with market returns", flush=True)

con.execute(f"""
CREATE OR REPLACE TEMP TABLE ret_mkt AS
SELECT
    r.permno,
    r.ret_date,
    r.ret,
    r.retx,
    r.prc,
    r.vol,
    r.shrcd,
    r.exchcd,
    m.vwretd,
    m.ewretd,
    r.ret - m.vwretd AS abret_vw,
    r.ret - m.ewretd AS abret_ew
FROM read_parquet('{ret_filtered_parquet}') AS r
LEFT JOIN mkt AS m
    ON r.ret_date = m.ret_date
WHERE r.ret IS NOT NULL
""")

print("Step 9 done.", flush=True)


# ------------------------------------------------------------
# 10. Rank trading days within each PERMNO
# ------------------------------------------------------------

print("Step 10: ranking trading days", flush=True)

con.execute("""
CREATE OR REPLACE TEMP TABLE ret_ranked AS
SELECT
    *,
    ROW_NUMBER() OVER (
        PARTITION BY permno
        ORDER BY ret_date
    ) AS trade_day_id
FROM ret_mkt
""")

print("Step 10 done.", flush=True)


# ------------------------------------------------------------
# 11. Find event day 0 candidates
# ------------------------------------------------------------

print("Step 11: finding event day 0 candidates", flush=True)

con.execute("""
CREATE OR REPLACE TEMP TABLE event0_candidates AS
SELECT
    sl.*,
    r0.ret_date AS event_date,
    r0.trade_day_id AS event_trade_day_id,
    r0.shrcd,
    r0.exchcd,
    r0.prc,
    r0.vol,
    r0.ret AS ret_event0
FROM sample_linked AS sl
LEFT JOIN LATERAL (
    SELECT
        rr.ret_date,
        rr.trade_day_id,
        rr.shrcd,
        rr.exchcd,
        rr.prc,
        rr.vol,
        rr.ret
    FROM ret_ranked AS rr
    WHERE rr.permno = sl.permno
      AND rr.ret_date >= sl.filing_dt
      AND rr.ret_date <= sl.filing_dt + INTERVAL 3 DAY
    ORDER BY rr.ret_date
    LIMIT 1
) AS r0 ON true
""")

print("Step 11 done.", flush=True)


# ------------------------------------------------------------
# 12. Choose one best PERMNO per filing
# ------------------------------------------------------------

print("Step 12: choosing one best PERMNO per filing", flush=True)

con.execute("""
CREATE OR REPLACE TEMP TABLE event0 AS
SELECT *
FROM (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY row_id
            ORDER BY
                CASE WHEN event_date IS NOT NULL THEN 0 ELSE 1 END,
                CASE WHEN shrcd IN (10, 11) THEN 0 ELSE 1 END,
                CASE WHEN exchcd IN (1, 2, 3) THEN 0 ELSE 1 END,
                ABS(prc) DESC NULLS LAST,
                permno
        ) AS permno_rank
    FROM event0_candidates
) ranked
WHERE permno_rank = 1
""")

print("Step 12 done.", flush=True)


# ------------------------------------------------------------
# 13. Build event-window return table
# ------------------------------------------------------------

print("Step 13: building event-window return table", flush=True)

con.execute("""
CREATE OR REPLACE TEMP TABLE event_returns AS
SELECT
    e.*,
    rr.ret_date,
    rr.trade_day_id - e.event_trade_day_id AS event_day,
    rr.ret,
    rr.retx,
    rr.vwretd,
    rr.ewretd,
    rr.abret_vw,
    rr.abret_ew
FROM event0 AS e
LEFT JOIN ret_ranked AS rr
    ON e.permno = rr.permno
   AND rr.trade_day_id BETWEEN e.event_trade_day_id - 2
                           AND e.event_trade_day_id + 2
""")

print("Step 13 done.", flush=True)


# ------------------------------------------------------------
# 14. Aggregate CAR variables
# ------------------------------------------------------------

print("Step 14: aggregating CAR variables", flush=True)

if out_path.exists():
    out_path.unlink()

con.execute(f"""
COPY (
    SELECT
        row_id,
        cik,
        name,
        tickers,
        exchanges,
        entity_type,
        sic,
        state_of_incorporation,
        filing_date,
        report_date,
        url,

        permno,
        permco,
        gvkey,
        linktype,
        linkdt,
        linkenddt,
        event_date,

        SUM(CASE WHEN event_day = 0 THEN ret ELSE NULL END) AS ret_0,
        SUM(CASE WHEN event_day = 0 THEN vwretd ELSE NULL END) AS mktret_vw_0,
        SUM(CASE WHEN event_day = 0 THEN ewretd ELSE NULL END) AS mktret_ew_0,
        SUM(CASE WHEN event_day = 0 THEN abret_vw ELSE NULL END) AS abret_vw_0,
        SUM(CASE WHEN event_day = 0 THEN abret_ew ELSE NULL END) AS abret_ew_0,

        SUM(CASE WHEN event_day BETWEEN 0 AND 1 THEN ret ELSE NULL END) AS rawret_0_p1,
        SUM(CASE WHEN event_day BETWEEN -1 AND 1 THEN ret ELSE NULL END) AS rawret_m1_p1,
        SUM(CASE WHEN event_day BETWEEN -2 AND 2 THEN ret ELSE NULL END) AS rawret_m2_p2,

        SUM(CASE WHEN event_day BETWEEN 0 AND 1 THEN abret_vw ELSE NULL END) AS car_vw_0_p1,
        SUM(CASE WHEN event_day BETWEEN -1 AND 1 THEN abret_vw ELSE NULL END) AS car_vw_m1_p1,
        SUM(CASE WHEN event_day BETWEEN -2 AND 2 THEN abret_vw ELSE NULL END) AS car_vw_m2_p2,

        SUM(CASE WHEN event_day BETWEEN 0 AND 1 THEN abret_ew ELSE NULL END) AS car_ew_0_p1,
        SUM(CASE WHEN event_day BETWEEN -1 AND 1 THEN abret_ew ELSE NULL END) AS car_ew_m1_p1,
        SUM(CASE WHEN event_day BETWEEN -2 AND 2 THEN abret_ew ELSE NULL END) AS car_ew_m2_p2,

        COUNT(CASE WHEN event_day = 0 THEN ret END) AS n_ret_0,
        COUNT(CASE WHEN event_day BETWEEN 0 AND 1 THEN ret END) AS n_ret_0_p1,
        COUNT(CASE WHEN event_day BETWEEN -1 AND 1 THEN ret END) AS n_ret_m1_p1,
        COUNT(CASE WHEN event_day BETWEEN -2 AND 2 THEN ret END) AS n_ret_m2_p2

    FROM event_returns
    GROUP BY
        row_id,
        cik,
        name,
        tickers,
        exchanges,
        entity_type,
        sic,
        state_of_incorporation,
        filing_date,
        report_date,
        url,
        permno,
        permco,
        gvkey,
        linktype,
        linkdt,
        linkenddt,
        event_date
) TO '{out_path}' WITH (HEADER, DELIMITER ',')
""")

print(f"Step 14 done. Saved to: {out_path}", flush=True)


# ------------------------------------------------------------
# 15. Export main analysis sample
# ------------------------------------------------------------

print("Step 15: exporting main analysis sample", flush=True)

if analysis_path.exists():
    analysis_path.unlink()

con.execute(f"""
COPY (
    SELECT
        row_id,
        cik,
        name,
        tickers,
        exchanges,
        entity_type,
        sic,
        state_of_incorporation,
        filing_date,
        report_date,
        url,

        permno,
        event_date,

        ret_0,
        abret_vw_0,
        car_vw_0_p1,
        car_vw_m1_p1,
        car_vw_m2_p2,

        n_ret_0,
        n_ret_0_p1,
        n_ret_m1_p1,
        n_ret_m2_p2
    FROM read_csv_auto('{out_path}', all_varchar = true)
    WHERE n_ret_m1_p1 = '3'
      AND car_vw_m1_p1 IS NOT NULL
) TO '{analysis_path}' WITH (HEADER, DELIMITER ',')
""")

print(f"Step 15 done. Saved to: {analysis_path}", flush=True)


# ------------------------------------------------------------
# 16. Final check
# ------------------------------------------------------------

print("Step 16: final check", flush=True)

summary = con.execute(f"""
SELECT
    COUNT(*) AS n_rows,
    COUNT(DISTINCT row_id) AS n_filings,
    COUNT(DISTINCT CASE WHEN permno IS NOT NULL THEN row_id END) AS n_with_permno,
    COUNT(DISTINCT CASE WHEN event_date IS NOT NULL THEN row_id END) AS n_with_event_date,
    COUNT(DISTINCT CASE WHEN n_ret_0_p1 = '2' THEN row_id END) AS n_complete_0_p1,
    COUNT(DISTINCT CASE WHEN n_ret_m1_p1 = '3' THEN row_id END) AS n_complete_m1_p1,
    COUNT(DISTINCT CASE WHEN n_ret_m2_p2 = '5' THEN row_id END) AS n_complete_m2_p2
FROM read_csv_auto('{out_path}', all_varchar = true)
""").df()

print(summary.to_string(index=False), flush=True)

print("All done.", flush=True)