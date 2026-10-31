#!/usr/bin/env bash
# Unity Catalog grants for the deploy service principal (run-as identity of the prod job) on the
# demand-forecasting catalog. Default: prints the SQL to run in the SQL editor as the catalog owner.
# --apply sets the same grants through the Unity Catalog grants API with the Databricks CLI; --check reads
# the effective grants back (read-only). The application id comes from the environment and is never
# written to the repository.
#
# Required: DFM_DEPLOY_SP (application id of the service principal)
# Optional: DFM_CATALOG (default dfm), DATABRICKS_CONFIG_PROFILE
# Usage: infra/grant_deploy_sp.sh            print the grant SQL
#        infra/grant_deploy_sp.sh --apply    apply the grants with the CLI
#        infra/grant_deploy_sp.sh --check    read the effective grants back
set -euo pipefail

SP="${DFM_DEPLOY_SP:?set DFM_DEPLOY_SP to the service principal application id}"
CATALOG="${DFM_CATALOG:-dfm}"
DATA_SCHEMAS=(bronze silver gold monitoring)
DATA_PRIVS=(USE_SCHEMA SELECT MODIFY CREATE_TABLE CREATE_MATERIALIZED_VIEW)

# securable type, full name, privileges
GRANTS=("catalog ${CATALOG} USE_CATALOG")
for s in "${DATA_SCHEMAS[@]}"; do GRANTS+=("schema ${CATALOG}.${s} ${DATA_PRIVS[*]}"); done
GRANTS+=("schema ${CATALOG}.ml USE_SCHEMA CREATE_MODEL")
GRANTS+=("schema ${CATALOG}.landing USE_SCHEMA")
GRANTS+=("volume ${CATALOG}.landing.exports READ_VOLUME WRITE_VOLUME")

case "${1:-}" in
  --check)
    for g in "${GRANTS[@]}"; do
      read -r kind name _ <<<"${g}"
      printf '%s %s: ' "${kind}" "${name}"
      databricks grants get-effective "${kind}" "${name}" --principal "${SP}" -o json \
        | python -c "import json,sys; d=json.load(sys.stdin); print(sorted({p['privilege'] for a in d.get('privilege_assignments', []) for p in a.get('privileges', [])}))"
    done
    ;;
  --apply)
    for g in "${GRANTS[@]}"; do
      read -r kind name privs <<<"${g}"
      add=$(python -c "import json,sys; print(json.dumps(sys.argv[1].split()))" "${privs}")
      databricks grants update "${kind}" "${name}" \
        --json "{\"changes\": [{\"principal\": \"${SP}\", \"add\": ${add}}]}" > /dev/null
      echo "granted ${privs} on ${kind} ${name}"
    done
    ;;
  *)
    for g in "${GRANTS[@]}"; do
      read -r kind name privs <<<"${g}"
      sql_privs=$(python -c "import sys; print(', '.join(p.replace('_', ' ') for p in sys.argv[1].split()))" "${privs}")
      echo "GRANT ${sql_privs} ON ${kind^^} ${name} TO \`${SP}\`;"
    done
    ;;
esac
