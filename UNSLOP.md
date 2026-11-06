Backend :
- reuse a generic version of _database_error in the views instead of creating a custom version each time
- bearer token stuff and http response code stuff in tus.py (and maybe elsewhere), those should either not exist or be placed in a more global context to avoid writing the same helpers in every file
- tus_proxy.py seems to do a lot of hand work, can't FastAPI (or an idiomatic package) be used instead ?
- _splat_generation_parameters should be a proper dataclass with .from_xxx() methods
- views/reconstruction_submissions.py doesn't have any endpoint and thus shouldn't be in /views/

Frontend :
- shitty validation wrappers (isRecord, isValidBuildingCreate, etc...)
- things that are emit + ref in parent instead of a dedicated defineModel (like valid in BuildingPicker.vue)
- polling logic works for updates in the buildings and reconstruction queries, but it's quite ugly to put it straight in there
- building error messages in a less obnoxious way (cf mutations/buildings.ts)
- duplication between all the record pages
- auto-polling queries, like useMyUploadsQuery() work by re-fetching the whole list over and over until no item is pending. That means a lot of wasted traffic for page_size >>> pending_items_count. We should probably poll only on the affected IDs, meaning probably having backend endpoints that accept a list of IDs, to refetch only those. Or, having a only_pending flags on the list endpoint (probably easier ?).
