Backend :
- reuse a generic version of _database_error in the views instead of creating a custom version each time
- bearer token stuff and http response code stuff in tus.py (and maybe elsewhere), those should either not exist or be placed in a more global context to avoid writing the same helpers in every files
- tus_proxy.py seems to do a lot of hand work, can't FastAPI (or an idiomatic package) be used instead ?
- _splat_generation_parameters should be a proper dataclas with .from_xxx() methods
- views/reconstruction_submissions.py doesn't have any endpoint and thus shouldn't be in /views/

Frontend :
- shitty validation wrappers (isRecord, isValidBuildingCreate, etc...)
- things that are emit + ref in parent instead of a dedicated defineModel (like valid in BuildingPicker.vue)
- polling logic works for updates in the buildings and reconstruction queries, but it's quite ugly to put it straight in there
- check if this worker url thing is necessary in the maps
- building error messages in a less obnoxious way (cf mutations/buildings.ts)
- check if we can make an helper to wire directly a query -> q-pagination
- resumableDownload.ts is super ugly, maybe refactor (low priority)
