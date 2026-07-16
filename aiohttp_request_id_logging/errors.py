class RequestIdKeyAlreadySetError (Exception):
    '''
    Raised when the request already contains a request id.

    This most likely means that request_id_middleware is applied twice,
    or that something else also sets the request id in the request.
    '''

    def __init__(self, existing_request_id):
        super().__init__(
            f'The request already contains request id {existing_request_id!r} - '
            'request_id_middleware is most likely applied twice, '
            'or something else also sets the request id')
        self.existing_request_id = existing_request_id
