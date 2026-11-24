from pydantic import ValidationError
from scrapy.exceptions import DropItem

from daii.bronze.items import bronze_item


class ValidatePipeline:
    """Valida cada ítem contra el contrato bronze. Los inválidos se descartan y cuentan en stats (lo revisa quality)."""

    def process_item(self, item, spider):
        try:
            return bronze_item.validate_python(item).model_dump(mode='json')
        except ValidationError as e:
            spider.crawler.stats.inc_value(f'daii/invalid_item/{item.get("tipo")}')
            raise DropItem(f'ítem inválido: {e}') from e
