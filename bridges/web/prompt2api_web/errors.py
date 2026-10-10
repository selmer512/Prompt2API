class BridgeError(Exception):
    def __init__(self, message: str, code: str = "provider_error", status: int = 502):
        super().__init__(message)
        self.code = code
        self.status = status

    def payload(self):
        return {"error": {"message": str(self), "type": self.code, "code": self.code}}
