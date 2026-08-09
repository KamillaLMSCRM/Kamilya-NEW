import asyncio

from app.modules.learning_cycles.service import recover_due

if __name__ == "__main__":
    asyncio.run(recover_due())
