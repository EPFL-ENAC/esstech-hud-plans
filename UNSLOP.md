Backend :
- reuse a generic version of _database_error in the views instead of creating a custom version each time

Frontend :
- shitty validation wrappers (isRecord, isValidBuildingCreate, etc...)
- things that are emit + ref in parent instead of a dedicated defineModel (like valid in BuildingPicker.vue)
- polling logic works for updates in the buildings and reconstruction queries, but it's quite ugly to put it straight in there
- check if this worker url thing is necessary in the maps
- building error messages in a less obnoxious way (cf mutations/buildings.ts)
- check if we can make an helper to wire directly a query -> q-pagination
