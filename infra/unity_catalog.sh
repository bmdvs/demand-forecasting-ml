#!/usr/bin/env bash
# Unity Catalog objects for the demand-forecasting platform: catalog, schemas and the landing volume, as
# Databricks CLI commands so the setup can be reproduced, and a read-only check of an existing setup.
# The storage credential and the two external locations are shared with the workspace's other catalogs;
# this script only verifies them and never creates or changes them. Identifiers come from environment
# variables, never from the repository.
#
# Required: DFM_STORAGE_ACCOUNT (ADLS Gen2 account name)
# Optional: DFM_CATALOG (default dfm), DFM_DEV_CATALOG (default dfm_dev), DFM_CREDENTIAL (default cred_pdm),
#           DFM_LANDING_LOCATION (default loc_pdm_landing), DFM_MANAGED_LOCATION (default loc_pdm_managed)
# Usage: infra/unity_catalog.sh [PROFILE]              creates the catalog, schemas and landing volume
#        infra/unity_catalog.sh [PROFILE] --check      read-only verification against the expected settings
#        infra/unity_catalog.sh [PROFILE] --dev        creates the development catalog (bundle dev target):
#                                                      the same schemas and a managed volume landing.autoloader
#                                                      for Auto Loader schema tracking; dev reads the prod
#                                                      landing volume
#        infra/unity_catalog.sh [PROFILE] --dev-check  read-only verification of the development catalog
#
# Catalogs take their managed location from a folder of the managed container; schemas have no locations
# of their own. The landing volume is external, on a dfm/ folder of the landing container.
set -euo pipefail

PROFILE="${1:-${DATABRICKS_CONFIG_PROFILE:-DEFAULT}}"
MODE="${2:-}"
CATALOG="${DFM_CATALOG:-dfm}"
DEV_CATALOG="${DFM_DEV_CATALOG:-dfm_dev}"
CREDENTIAL="${DFM_CREDENTIAL:-cred_pdm}"
LOC_LANDING="${DFM_LANDING_LOCATION:-loc_pdm_landing}"
LOC_MANAGED="${DFM_MANAGED_LOCATION:-loc_pdm_managed}"
ACCOUNT="${DFM_STORAGE_ACCOUNT:?set DFM_STORAGE_ACCOUNT}"
LANDING="abfss://landing@${ACCOUNT}.dfs.core.windows.net/"
MANAGED="abfss://managed@${ACCOUNT}.dfs.core.windows.net/"
SCHEMAS=(landing bronze silver gold ml monitoring)
db() { databricks --profile "${PROFILE}" "$@"; }

if [[ "${MODE}" == "--check" || "${MODE}" == "--dev-check" ]]; then
  fail=0
  expect() {
    local what="$1" got="$2" want="$3"
    if [[ "${got%/}" == "${want%/}" ]]; then echo "ok    ${what}: ${got}"; else echo "DIFF  ${what}: got '${got}', expected '${want}'"; fail=1; fi
  }
  field() { python -c "import json,sys; d=json.load(sys.stdin); print(d.get('$1') or '')"; }
  if [[ "${MODE}" == "--dev-check" ]]; then
    expect "catalog ${DEV_CATALOG} storage root" "$(db catalogs get "${DEV_CATALOG}" -o json | field storage_root)" "${MANAGED}${DEV_CATALOG}"
    for s in "${SCHEMAS[@]}"; do
      expect "schema ${DEV_CATALOG}.${s} storage root" "$(db schemas get "${DEV_CATALOG}.${s}" -o json | field storage_root)" ""
    done
    expect "volume ${DEV_CATALOG}.landing.autoloader type" "$(db volumes read "${DEV_CATALOG}.landing.autoloader" -o json | field volume_type)" "MANAGED"
    exit "${fail}"
  fi
  expect "credential ${CREDENTIAL}" "$(db storage-credentials get "${CREDENTIAL}" -o json | field name)" "${CREDENTIAL}"
  expect "${LOC_LANDING} url" "$(db external-locations get "${LOC_LANDING}" -o json | field url)" "${LANDING}"
  expect "${LOC_LANDING} credential" "$(db external-locations get "${LOC_LANDING}" -o json | field credential_name)" "${CREDENTIAL}"
  expect "${LOC_MANAGED} url" "$(db external-locations get "${LOC_MANAGED}" -o json | field url)" "${MANAGED}"
  expect "${LOC_MANAGED} credential" "$(db external-locations get "${LOC_MANAGED}" -o json | field credential_name)" "${CREDENTIAL}"
  expect "catalog ${CATALOG} storage root" "$(db catalogs get "${CATALOG}" -o json | field storage_root)" "${MANAGED}${CATALOG}"
  for s in "${SCHEMAS[@]}"; do
    expect "schema ${CATALOG}.${s} storage root" "$(db schemas get "${CATALOG}.${s}" -o json | field storage_root)" ""
  done
  expect "volume ${CATALOG}.landing.exports type" "$(db volumes read "${CATALOG}.landing.exports" -o json | field volume_type)" "EXTERNAL"
  expect "volume ${CATALOG}.landing.exports location" "$(db volumes read "${CATALOG}.landing.exports" -o json | field storage_location)" "${LANDING}${CATALOG}"
  exit "${fail}"
fi

if [[ "${MODE}" == "--dev" ]]; then
  db catalogs create "${DEV_CATALOG}" --storage-root "${MANAGED}${DEV_CATALOG}" \
    --comment "Development catalog for the demand-forecasting platform (bundle dev target)"
  for s in "${SCHEMAS[@]}"; do db schemas create "${s}" "${DEV_CATALOG}"; done
  db volumes create "${DEV_CATALOG}" landing autoloader MANAGED --comment "Auto Loader schema tracking for the dev pipeline"
  exit 0
fi

db catalogs create "${CATALOG}" --storage-root "${MANAGED}${CATALOG}" \
  --comment "Demand forecasting and inventory planning: ERP extracts, warehouse, models and monitoring"
for s in "${SCHEMAS[@]}"; do db schemas create "${s}" "${CATALOG}"; done
db volumes create "${CATALOG}" landing exports EXTERNAL --storage-location "${LANDING}${CATALOG}" \
  --comment "Source-system extracts as delivered: ERP, WMS, purchasing, remediation records and reference data"
