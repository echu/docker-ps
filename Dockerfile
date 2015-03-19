#
# dockerps
#
# https://github.com/echu/dockerps
#

# Base image
FROM ubuntu

# Update apt
RUN apt-get update --fix-missing

# Install git and curl
RUN apt-get install -y git curl

# Install python
RUN \
    apt-get install -y python python-dev

# Install pip by hand (to get latest)
RUN \
    curl -o get-pip.py https://bootstrap.pypa.io/get-pip.py && \
    python get-pip.py

ADD requirements.txt requirements.txt

# Install dependencies
RUN \
    pip install -r requirements.txt

ADD src app

WORKDIR app

CMD python serve.py

