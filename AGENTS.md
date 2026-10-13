## Migrations

Do not handwrite the migrations, prefer using the commands defined in the Makefiles.

## Formatting

Make sure the code is always formatted in a readable way. For instance this :

```python
async def list(
    self, *, user_id: UUID,
    offset: int = 0, limit: int = 100,
    sort_order: Literal["asc", "desc"] = "desc",
) -> list[UserUploads]: ...
```

is very bad because the arguments of the function are spread both horizontal or vertically, either choose :
```py
def something(arg2, arg2)
```
for short arg lists or :
```py
async def list(
    self,
    *,
    user_id: UUID,
    offset: int = 0,
    limit: int = 100,
    sort_order: Literal["asc", "desc"] = "desc",
) -> list[UserUploads]: ...
```
for long ones
