from . import main
import asyncio

def main_entry():
    """Main entry point for the package."""
    asyncio.run(main.main())

# Expose main function
__all__ = ['main_entry', 'main']
