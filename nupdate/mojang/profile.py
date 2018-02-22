from nupdate.utils import Namespace


class MojangSelecteduserJson(Namespace):
    @property
    def account(self):
        return self.get("account")

    @property
    def profile(self):
        return self.get("profile")


class MojangAuthentcationProfileJson(Namespace):
    def __init__(self, selectedUser: MojangSelecteduserJson, data):
        self.selectedUser = selectedUser
        super().__init__(data)

    @property
    def account(self):
        return self.selectedUser.account

    @property
    def auth_uuid(self):
        return self.selectedUser.profile

    @property
    def auth_access_token(self):
        return self.get("accessToken")

    @property
    def auth_player_name(self):
        return self.get("profiles", {}).get(self.selectedUser.profile, {}).get("displayName")

    @property
    def email(self):
        return self.get("username")


class MojangLauncherProfileJson(Namespace):
    @property
    def clientToken(self):
        return self.get("clientToken")

    @property
    def selectedUser(self):
        return MojangSelecteduserJson(self.get("selectedUser", {}))

    @property
    def selectedAccount(self) -> MojangAuthentcationProfileJson:
        selectedUser = self.selectedUser
        if selectedUser:
            profile_json = self.authenticationDatabase.get(selectedUser.account)
            if profile_json:
                profile = MojangAuthentcationProfileJson(selectedUser, data=profile_json)
                return profile

    @property
    def authenticationDatabase(self) -> dict:
        return self.get("authenticationDatabase", {})
