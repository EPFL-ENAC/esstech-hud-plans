Backend :
- reuse a generic version of _database_error in the views instead of creating a custom version each time

Frontend :
- shitty validation wrappers (isRecord, isValidBuildingCreate, etc...)
- things that are emit + ref in parent instead of a dedicated defineModel (like valid in BuildingPicker.vue)
