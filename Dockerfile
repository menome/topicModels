FROM innerlogic/python-pika:latest
RUN mkdir /srv/app
WORKDIR /srv/app
EXPOSE  8000
VOLUME ["/srv/app/config"]

# Install Dependencies
COPY /requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the code for the prod container.
# This seems to not cause any problems in dev when we mount a volume at this point.
COPY ./app app
COPY ./config config

CMD ["python", "/srv/app/app/server.py", "-p 8000"]