from redash.models import db, User
from playhouse.migrate import PostgresqlMigrator, migrate

if __name__ == '__main__':
    migrator = PostgresqlMigrator(db.database)

    with db.database.transaction():
        migrate(
            migrator.add_column('user', 'active', User.active),
            migrator.add_column('user', 'gg_args', User.gg_args),
        )
