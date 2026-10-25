import graphene


class Query(graphene.ObjectType):
    ping = graphene.String(required=True)
    version = graphene.String(required=True)

    def resolve_ping(root, info):
        return "pong"

    def resolve_version(root, info):
        return "0.1.0"


schema = graphene.Schema(query=Query)
