# To enable ssh & remote debugging on app service change the base image to the one below
# FROM mcr.microsoft.com/azure-functions/python:3.0-python3.9-appservice
FROM mcr.microsoft.com/azure-functions/python:3.0-python3.9

ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true


RUN apt-get update && apt-get install -y apt-utils 
RUN apt-get install -y python3-pip
RUN /usr/local/bin/python -m pip install --upgrade pip
RUN pip3 install azure-data-tables
RUN pip3 install azure-storage-file-datalake

COPY requirements.txt /
RUN pip install -r /requirements.txt
RUN pip install pandas
RUN pip install -U scikit-learn
RUN pip install pytz
RUN pip install beautifulsoup4
RUN pip install pika

COPY dataIngest.py ./

# CMD [ "python", "./dataIngest.py"]
