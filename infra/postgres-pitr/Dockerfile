FROM postgres:16-alpine

RUN apk add --no-cache pgbackrest

RUN mkdir -p /var/lib/pgbackrest /etc/pgbackrest /var/log/pgbackrest \
 && chown -R postgres:postgres /var/lib/pgbackrest /var/log/pgbackrest \
 && chmod 750 /var/lib/pgbackrest /var/log/pgbackrest

COPY pgbackrest.conf /etc/pgbackrest/pgbackrest.conf
COPY postgresql-pitr.conf /etc/postgresql/postgresql-pitr.conf
COPY docker-entrypoint-pitr.sh /usr/local/bin/docker-entrypoint-pitr.sh

RUN chmod +x /usr/local/bin/docker-entrypoint-pitr.sh \
 && chown postgres:postgres /etc/pgbackrest/pgbackrest.conf

ENTRYPOINT ["docker-entrypoint-pitr.sh"]
CMD ["postgres", "-c", "config_file=/etc/postgresql/postgresql-pitr.conf"]
