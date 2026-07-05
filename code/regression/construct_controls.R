# ============================================================
# Z. Li part: Construct Compustat control variables
# Project: 10-K Negative Tone and Market Reaction
# Current plan: LM_NegTone only
# ============================================================

library(tidyverse)

# ------------------------------------------------------------
# Step 1: Read Compustat annual data
# This step: read Compustat annual financial data downloaded from WRDS
# Note: do not upload this raw data to public GitHub
# ------------------------------------------------------------

comp <- read_csv("data/external/compustat_annual.csv")

# Make column names lowercase to avoid case-sensitivity issues
names(comp) <- tolower(names(comp))


# ------------------------------------------------------------
# Step 2: Clean identifiers and remove duplicate firm-years
# This step: clean company IDs and ensure only one row per gvkey-fyear
# ------------------------------------------------------------

comp_clean <- comp %>%
  mutate(
    gvkey = str_pad(as.character(gvkey), width = 6, pad = "0"),

    cik = as.character(cik),
    cik = str_replace(cik, "\\.0$", ""),
    cik = if_else(is.na(cik) | cik == "NA", NA_character_, str_pad(cik, width = 10, pad = "0")),

    # If the same firm-year has both INDL and FS, prefer INDL
    indfmt_priority = case_when(
      indfmt == "INDL" ~ 1,
      indfmt == "FS" ~ 2,
      TRUE ~ 3
    )
  ) %>%
  arrange(
    gvkey,
    fyear,
    indfmt_priority
  ) %>%
  group_by(gvkey, fyear) %>%
  slice(1) %>%
  ungroup()


# ------------------------------------------------------------
# Step 3: Construct control variables
# This step: generate regression control variables from Compustat raw variables
# ------------------------------------------------------------

controls <- comp_clean %>%
  mutate(
    # If debt variables are missing, treat them as 0
    dltt = replace_na(dltt, 0),
    dlc = replace_na(dlc, 0),

    # Market equity = fiscal-year-end price × common shares outstanding
    # Stock market equity = fiscal-year-end price × common shares outstanding
    market_equity = prcc_f * csho,

    # Firm size = log(total assets)
    # Company size = natural log of total assets
    size = log(at),

    # Book-to-market = common equity / market equity
    # Book-to-market ratio = common equity / market equity
    bm = ceq / market_equity,

    # Leverage = total debt / total assets
    # Leverage = (long-term debt + short-term debt) / total assets
    leverage = (dltt + dlc) / at,

    # ROA = net income / total assets
    # Profitability = net income / total assets
    roa = ni / at,

    # Loss dummy = 1 if net income is negative, otherwise 0
    # Loss indicator: 1 if net income < 0, otherwise 0
    loss = if_else(ni < 0, 1, 0),

    # Two-digit SIC industry code
    # Two-digit industry code, used for industry fixed effects
    sic2 = floor(as.numeric(sic) / 100)
  ) %>%
  filter(
    at > 0,
    market_equity > 0,
    fyear >= 2001,
    fyear <= 2024
  ) %>%
  select(
    gvkey,
    fyear,
    costat,
    indfmt,
    conm,
    tic,
    cusip,
    cik,
    sic,
    sic2,
    size,
    bm,
    leverage,
    roa,
    loss,
    market_equity,
    at,
    ceq,
    dlc,
    dltt,
    ni,
    csho,
    prcc_f
  )


# ------------------------------------------------------------
# Step 4: Check the controls dataset
# This step: check whether the generated control variables are reasonable
# ------------------------------------------------------------

glimpse(controls)

controls %>%
  summarise(
    n_obs = n(),
    n_firms = n_distinct(gvkey),
    min_year = min(fyear, na.rm = TRUE),
    max_year = max(fyear, na.rm = TRUE),
    duplicate_firm_years = sum(duplicated(paste(gvkey, fyear))),
    missing_size = sum(is.na(size)),
    missing_bm = sum(is.na(bm)),
    missing_leverage = sum(is.na(leverage)),
    missing_roa = sum(is.na(roa)),
    missing_loss = sum(is.na(loss))
  )


# ------------------------------------------------------------
# Step 5: Save controls
# This step: save control variables; the main regression will read this file later
# ------------------------------------------------------------

dir.create("data/generated/regression", recursive = TRUE, showWarnings = FALSE)

write_csv(controls, "data/generated/regression/controls.csv")
