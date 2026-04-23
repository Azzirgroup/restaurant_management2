from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

setup(
    name="restaurant_management",
    version="1.0.0",
    description="Restaurant Billing & Order Management for ERPNext",
    author="Restaurant Management",
    author_email="info@restaurant.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
