from aiofiles.os import remove


async def delete_temp_file(file_path):
    await remove(file_path)
