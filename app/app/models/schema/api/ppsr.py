from pydantic import BaseModel, Field

# from my domain to ppsr format


class Domain(BaseModel):
    name: str = Field()

    class Config:
        allow_population_by_field_name = True


p = Domain(name="cool")
print(p.dict())
print(p.dict(by_alias=True))

ppsr_alias = {"name": "projectId"}

for (k, v) in ppsr_alias.items():
    Domain.__fields__[k].alias = v

print(p.dict(by_alias=True))
# but we still need something... a validator that grabs stuff out of the content.
# cuz we dont want columns for all that stuff...
