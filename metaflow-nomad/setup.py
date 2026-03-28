from setuptools import find_namespace_packages, setup


version = "0.1.0"


setup(
    name="metaflow-nomad",
    version=version,
    description="Prototype Nomad extension for Metaflow",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Pranjali Singh",
    license="Apache Software License",
    packages=find_namespace_packages(include=["metaflow_extensions.*"]),
    python_requires=">=3.8",
    install_requires=["metaflow", "requests>=2.31.0"],
)
