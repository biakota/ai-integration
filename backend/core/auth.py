from rest_framework.authentication import TokenAuthentication


class BearerTokenAuthentication(TokenAuthentication):
    """Same as DRF's TokenAuthentication but accepts the `Bearer` keyword
    instead of `Token`. Plays well with the Swagger UI Authorize button,
    which auto-prefixes `Bearer ` for bearer schemes.
    """

    keyword = "Bearer"
