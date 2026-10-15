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
def something(arg1, arg2)
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


## Code style

### Dependency injection

Parameters that are given via FastAPI's dependency injection system (Depends()) should be explicit.

For example this is bad :
```py
UploadsService = Annotated[UserUploadsService, Depends(get_uploads_service)]

async def reconcile_head(
    response: httpx.Response,
    upload: UserUploads,
    uploads: UserUploadsService,
) -> None:
    ...
```

But this is good :
```py
async def reconcile_head(
    response: httpx.Response,
    upload: UserUploads,
    uploads: Annotated[UserUploadsService, Depends(get_uploads_service)],
) -> None:
    ...
```

The latter is much clearer, even if that introduces duplication.

### Backwards compatibility

When working on a feature, backward-compatibility considerations should be OPT-IN. If a new feature/fix introduces a breaking change, do not plan a backward compatibility layer unless I explicitly ask for it. You are welcome to ask if I want one, but do not assume it is the case. The priority is always given to simplicity, and understandability of the code.
