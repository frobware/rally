# Copyright 2013: Mirantis Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from rally.benchmark.scenarios import base
from rally.benchmark.scenarios.keystone import utils as kutils
from rally.benchmark import validation


class KeystoneBasic(kutils.KeystoneScenario):
    """Basic benchmark scenarios for Keystone."""

    @validation.number("name_length", minval=10)
    @validation.required_openstack(admin=True)
    @base.scenario(context={"admin_cleanup": ["keystone"]})
    def create_user(self, name_length=10, **kwargs):
        """Create a keystone user with random name.

        :param name_length: length of the random part of user name
        :param kwargs: Other optional parameters to create users like
                         "tenant_id", "enabled".
        """
        self._user_create(name_length=name_length, **kwargs)

    @validation.number("name_length", minval=10)
    @validation.required_openstack(admin=True)
    @base.scenario(context={"admin_cleanup": ["keystone"]})
    def create_delete_user(self, name_length=10, **kwargs):
        """Create a keystone user with random name and then delete it.

        :param name_length: length of the random part of user name
        :param kwargs: Other optional parameters to create users like
                         "tenant_id", "enabled".
        """
        user = self._user_create(name_length=name_length, **kwargs)
        self._resource_delete(user)

    @validation.number("name_length", minval=10)
    @validation.required_openstack(admin=True)
    @base.scenario(context={"admin_cleanup": ["keystone"]})
    def create_tenant(self, name_length=10, **kwargs):
        """Create a keystone tenant with random name.

        :param name_length: length of the random part of tenant name
        :param kwargs: Other optional parameters
        """
        self._tenant_create(name_length=name_length, **kwargs)

    @validation.number("name_length", minval=10)
    @validation.number("users_per_tenant", minval=1)
    @validation.required_openstack(admin=True)
    @base.scenario(context={"admin_cleanup": ["keystone"]})
    def create_tenant_with_users(self, users_per_tenant, name_length=10,
                                 **kwargs):
        """Create a keystone tenant and several users belonging to it.

        :param name_length: length of the random part of tenant/user name
        :param users_per_tenant: number of users to create for the tenant
        :param kwargs: Other optional parameters for tenant creation
        :returns: keystone tenant instance
        """
        tenant = self._tenant_create(name_length=name_length, **kwargs)
        self._users_create(tenant, users_per_tenant=users_per_tenant,
                           name_length=name_length)

    @validation.number("name_length", minval=10)
    @validation.required_openstack(admin=True)
    @base.scenario(context={"admin_cleanup": ["keystone"]})
    def create_and_list_users(self, name_length=10, **kwargs):
        """Create a keystone user with random name and list all users.

        :param name_length: length of the random part of user name
        :param kwargs: Other optional parameters to create users like
                         "tenant_id", "enabled".
        """
        self._user_create(name_length=name_length, **kwargs)
        self._list_users()

    @validation.number("name_length", minval=10)
    @validation.required_openstack(admin=True)
    @base.scenario(context={"admin_cleanup": ["keystone"]})
    def create_and_list_tenants(self, name_length=10, **kwargs):
        """Create a keystone tenant with random name and list all tenants.

        :param name_length: length of the random part of tenant name
        :param kwargs: Other optional parameters
        """
        self._tenant_create(name_length=name_length, **kwargs)
        self._list_tenants()

    @validation.required_openstack(admin=True)
    @base.scenario(context={"admin_cleanup": ["keystone"]})
    def get_entities(self):
        """Get instance of a tenant, user, role and service by id's."""
        tenant = self._tenant_create(name_length=5)
        user = self._user_create(name_length=10)
        role = self._role_create()
        self._get_tenant(tenant.id)
        self._get_user(user.id)
        self._get_role(role.id)
        service = self._get_service_by_name("keystone")
        self._get_service(service.id)
