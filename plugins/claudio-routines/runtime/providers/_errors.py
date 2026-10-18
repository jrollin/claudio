PAGE_CAP_PARTIAL = "page cap"


class SourceUnreadable(Exception):
    def __init__(self, reason, status=None):
        super().__init__(reason)
        self.status = status


class PartialRead(SourceUnreadable):
    def __init__(self, why):
        super().__init__(f"partial: {why}")
        self.why = why


class CredentialsMissing(SourceUnreadable):
    pass
