from allauth.account.adapter import DefaultAccountAdapter


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        """Nobody signs up. Staff are invited by the owner; portal users by staff."""
        return False
