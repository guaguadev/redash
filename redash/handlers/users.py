import time
from flask import request
from flask_restful import abort
from funcy import project
from peewee import IntegrityError
import urllib2
import json

from redash import models
from redash.permissions import require_permission, require_admin_or_owner, is_admin_or_owner, \
    require_permission_or_owner, require_admin
from redash.handlers.base import BaseResource, require_fields, get_object_or_404

from redash.authentication.account import invite_link_for_user, send_invite_email, send_password_reset_email


def invite_user(org, inviter, user):
    invite_url = invite_link_for_user(user)
    send_invite_email(inviter, user, invite_url, org)
    return invite_url

def requestUserByEmail(email):
    try:
        url = urllib2.urlopen('http://slapi.guaguaxiche.com/slapi/redash/getuserbyemail?email=%s' % email)
        content = url.read()
        return json.loads(content)
    except Exception as e:
        return {'code': -1, 'message': u'用户信息查询失败'}

class UserListResource(BaseResource):
    @require_permission('list_users')
    def get(self):
        return [u.to_dict() for u in models.User.all(self.current_org)]

    @require_admin
    def post(self):
        req = request.get_json(force=True)
        require_fields(req, ('name', 'email'))

        user = models.User(org=self.current_org,
                           name=req['name'],
                           email=req['email'],
                           groups=[self.current_org.default_group.id])

        try:
            userinfo = requestUserByEmail(req['email'])
            if userinfo['code'] != 0:
                abort(400, message=userinfo['message'])
            else:
                user.active = True
                user.name = userinfo['username']
                user.gg_args = {'cities': userinfo.cities}
            user.save()
        except IntegrityError as e:
            if "email" in e.message:
                abort(400, message='Email already taken.')

            abort(500)

        self.record_event({
            'action': 'create',
            'timestamp': int(time.time()),
            'object_id': user.id,
            'object_type': 'user'
        })

        invite_url = invite_user(self.current_org, self.current_user, user)

        d = user.to_dict()
        d['invite_link'] = invite_url

        return d


class UserInviteResource(BaseResource):
    @require_admin
    def post(self, user_id):
        user = models.User.get_by_id_and_org(user_id, self.current_org)
        invite_url = invite_user(self.current_org, self.current_user, user)

        d = user.to_dict()
        d['invite_link'] = invite_url

        return d


class UserResetPasswordResource(BaseResource):
    @require_admin
    def post(self, user_id):
        user = models.User.get_by_id_and_org(user_id, self.current_org)
        reset_link = send_password_reset_email(user)


class UserResource(BaseResource):
    def get(self, user_id):
        require_permission_or_owner('list_users', user_id)
        user = get_object_or_404(models.User.get_by_id_and_org, user_id, self.current_org)

        return user.to_dict(with_api_key=is_admin_or_owner(user_id))

    def post(self, user_id):
        require_admin_or_owner(user_id)
        user = models.User.get_by_id_and_org(user_id, self.current_org)

        req = request.get_json(True)

        params = project(req, ('email', 'name', 'password', 'old_password', 'groups'))

        if 'password' in params and 'old_password' not in params:
            abort(403, message="Must provide current password to update password.")

        if 'old_password' in params and not user.verify_password(params['old_password']):
            abort(403, message="Incorrect current password.")

        if 'password' in params:
            user.hash_password(params.pop('password'))
            params.pop('old_password')

        if 'groups' in params and not self.current_user.has_permission('admin'):
            abort(403, message="Must be admin to change groups membership.")

        try:
            user.update_instance(**params)
        except IntegrityError as e:
            if "email" in e.message:
                message = "Email already taken."
            else:
                message = "Error updating record"

            abort(400, message=message)

        self.record_event({
            'action': 'edit',
            'timestamp': int(time.time()),
            'object_id': user.id,
            'object_type': 'user',
            'updated_fields': params.keys()
        })

        return user.to_dict(with_api_key=is_admin_or_owner(user_id))


