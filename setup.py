import setuptools

setuptools.setup(
    name='ntd_api',
    version='0.0.1',
    url='https://ntd.artrabbit.studio/',
    maintainer='ArtRabbit',
    maintainer_email='support@artrabbit.com',
    description='NTD disease simulation web API',
    long_description='Web API for executing specific NTD disease simulator model runs in Google Cloud Run',
    packages=setuptools.find_packages(),
    python_requires='>=3.6',
    install_requires=[
        'flask', 'flask_cors', # to run Flask API
        'google-cloud-storage', 'gcsfs', 'fsspec', # for cloud storage inc. via pandas/pickle
        'gunicorn', # for running under WSGI
        'pandas', # for CSV read/write
        'trachoma @ git+https://github.com/ArtRabbitStudio/ntd-model-trachoma.git@develop',
        'sth_simulation @ git+https://github.com/ArtRabbitStudio/ntd-model-sth.git@updated-params-20210322a'
    ],
    include_package_data=True
)
