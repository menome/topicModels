FROM innerlogic/python-pika:latest

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt


# Bundle app source
COPY app/server.py /src/server.py
#COPY app/classes/modeler.py /src/classes/modeler.py
#COPY app/classes/modeler.py /src/classes/consumer.py
#COPY app/classes/__init__.py /src/classes/__init__.py

#bundle config and data
COPY config/* /config/
COPY config/wiki_Model/en_wiki_001.dict /config/wiki_Model/en_wiki_001.dict
COPY config/wiki_Model/en_wiki_001.lda /config/wiki_Model/en_wiki_001.lda
COPY config/wiki_Model/en_wiki_001.lda.expElogbeta.npy /config/wiki_Model/en_wiki_001.lda.expElogbeta.npy
COPY config/wiki_Model/en_wiki_001.lda.id2word /config/wiki_Model/en_wiki_001.lda.id2word
COPY config/wiki_Model/en_wiki_001.lda.state /config/wiki_Model/en_wiki_001.lda.state

WORKDIR /run

EXPOSE  8000
CMD ["python", "/src/server.py", "-p 8000"]