# (c) 2012-2018, Ansible by Red Hat
#
# This file is part of Ansible Galaxy
#
# Ansible Galaxy is free software: you can redistribute it and/or modify
# it under the terms of the Apache License as published by
# the Apache Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# Ansible Galaxy is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# Apache License for more details.
#
# You should have received a copy of the Apache License
# along with Galaxy.  If not, see <http://www.apache.org/licenses/>.

import collections
import json
import re

import marshmallow as mm
from marshmallow import fields
from marshmallow import validate
import attr
import semantic_version

from galaxy import constants
from galaxy.common import schema
from galaxy.importer.utils import git
from galaxy.importer.utils import readme as readmeutils
from galaxy.importer.utils import spdx_licenses
from galaxy.main import models

SHA1_LEN = 40

# ---------------------------------------------------------

PlatformInfo = collections.namedtuple(
    'PlatformInfo', ['name', 'versions'])
DependencyInfo = collections.namedtuple(
    'DependencyInfo', ['namespace', 'name'])
VideoLink = collections.namedtuple(
    'VideoLink', ['url', 'description'])


def convert_none_to_empty_dict(val):
    ''' if val is None, return an empty dict'''

    # if val is not a dict or val 'None' return val
    # and let the validators raise errors later
    if val is None:
        return {}
    return val


class Content(object):
    """Represents common content data."""

    def __init__(self, name, path, content_type,
                 original_name=None, description='', readme=None,
                 role_meta=None, metadata=None, scores=None):
        self.name = name
        self.original_name = original_name or name
        self.path = path
        self.content_type = content_type
        self.description = description
        self.readme = readme
        self.role_meta = role_meta
        self.metadata = metadata or {}
        self.scores = scores


class Repository(object):
    """Represents repository metadata."""

    def __init__(self, branch, commit, format, contents,
                 readme=None, name=None, description=None, quality_score=None):
        self.branch = branch
        self.commit = commit
        self.format = format
        self.contents = contents
        self.readme = readme
        self.name = name
        self.description = description
        self.quality_score = quality_score


@attr.s(frozen=True)
class BaseCollectionInfo(object):
    '''Represents collection_info metadata in collection manifest.

    Includes data validation expected when collection is built.
    '''

    namespace = attr.ib(default=None)
    name = attr.ib(default=None)
    version = attr.ib(default=None)
    license = attr.ib(factory=list)
    description = attr.ib(default=None)

    repository = attr.ib(default=None)
    documentation = attr.ib(default=None)
    homepage = attr.ib(default=None)
    issues = attr.ib(default=None)

    authors = attr.ib(factory=list)
    tags = attr.ib(factory=list)

    license_file = attr.ib(
        default=None,
        validator=attr.validators.optional(attr.validators.instance_of(str)))
    readme = attr.ib(
        default=None,
        validator=attr.validators.optional(attr.validators.instance_of(str)))

    dependencies = attr.ib(factory=dict,
                           converter=convert_none_to_empty_dict)

    @property
    def label(self):
        return '%s.%s' % (self.namespace, self.name)

    @staticmethod
    def value_error(msg):
        raise ValueError("Invalid collection metadata. %s" % msg)

    @namespace.validator
    @name.validator
    @version.validator
    def _check_required(self, attribute, value):
        '''Check that value is present'''
        if not value:
            self.value_error("'%s' is required" % attribute.name)

    @version.validator
    def _check_version_format(self, attribute, value):
        '''Check that version is in semantic version format'''
        if not semantic_version.validate(value):
            self.value_error("Expecting 'version' to be in semantic version "
                             "format, instead found '%s'." % value)

    @authors.validator
    @tags.validator
    @license.validator
    def _check_list_of_str(self, attribute, value):
        '''Check that value is a list of strings'''
        err_msg = "Expecting '%s' to be a list of strings"
        if not isinstance(value, list):
            self.value_error(err_msg % attribute.name)
        for list_item in value:
            if not isinstance(list_item, str):
                self.value_error(err_msg % attribute.name)

    @license.validator
    def _check_licenses(self, attribute, value):
        '''Check that all licenses in license list are valid'''
        # load or return already loaded data
        valid_license_ids = spdx_licenses.get_spdx()

        invalid_licenses = [license_id for license_id in value
                            if not self._is_valid_license_id(
                                license_id, valid_license_ids)]
        if invalid_licenses:
            self.value_error(
                "Expecting 'license' to be a list of valid SPDX license "
                "identifiers, instead found invalid license identifiers: '%s' "
                "in 'license' value %s. "
                "For more info, visit https://spdx.org" %
                (','.join(invalid_licenses), value))

    @staticmethod
    def _is_valid_license_id(license_id, valid_license_ids):
        '''Check if license_id is valid and non-deprecated SPDX ID'''
        if license_id is None:
            return False

        valid = valid_license_ids.get(license_id, None)
        if valid is None:
            return False

        # license was in list, but is deprecated
        if valid and valid.get('deprecated', None):
            return False

        return True

    @dependencies.validator
    def _check_dependencies_type(self, attribute, value):
        '''Check type of dependencies dictionary and its contents'''
        if not isinstance(value, dict) or value is None:
            self.value_error("Expecting '%s' to be a dict" % attribute.name)
        for k, v in value.items():
            if not isinstance(k, str) or not isinstance(v, str):
                self.value_error("Expecting dict key and value to be strings")

    @tags.validator
    def _check_tags(self, attribute, value):
        '''Check value against tag regular expression'''
        for tag in value:
            # TODO update tag format once resolved
            # https://github.com/ansible/galaxy/issues/1563
            if not re.match(constants.TAG_REGEXP, tag):
                self.value_error("'tag' has invalid format: %s" % tag)

    @namespace.validator
    @name.validator
    def _check_name(self, attribute, value):
        '''Check value against name regular expression'''
        if not re.match(constants.NAME_REGEXP, value):
            self.value_error("'%s' has invalid format: %s" %
                             (attribute.name, value))

    def __attrs_post_init__(self):
        '''Checks called post init validation'''
        self._check_license_or_license_file(self.license, self.license_file)

    def _check_license_or_license_file(self, license_ids, license_file):
        '''Confirm presence of either license or license_file'''
        if license_ids or license_file:
            return
        self.value_error(
            "Valid values for 'license' or 'license_file' are required. "
            "But 'license' (%s) and 'license_file' (%s) were invalid." %
            (license_ids, license_file))


@attr.s(frozen=True)
class GalaxyCollectionInfo(BaseCollectionInfo):
    '''Represents collection_info metadata in galaxy.

    Includes additional data validation that is specific to galaxy.
    '''

    def get_json(self):
        return self.__dict__

    def _check_required(self, name):
        '''Check that value is present'''
        if not getattr(self, name):
            self.value_error("'%s' is required by galaxy" % name)

    def _check_non_null_str(self, name):
        '''Check that if value is present, it must be a string'''
        value = getattr(self, name)
        if value is not None and not isinstance(value, str):
            self.value_error("'%s' must be a string" % name)

    def _check_dependencies(self):
        '''Check dependencies and matching version present in database'''
        for dep_col, ver_spec in self.dependencies.items():
            ns_name, name = dep_col.split('.')

            if ns_name == self.namespace and name == self.name:
                self.value_error('Cannot have self dependency')

            try:
                ns = models.Namespace.objects.get(name=ns_name)
            except models.Namespace.DoesNotExist:
                self.value_error('Dependency namespace not in '
                                 'galaxy: %s' % dep_col)
            try:
                col = models.Collection.objects.get(
                    namespace=ns.pk,
                    name=name,
                )
            except models.Collection.DoesNotExist:
                self.value_error('Dependency collection not in '
                                 'galaxy: %s' % dep_col)

            try:
                spec = semantic_version.Spec(ver_spec)
            except ValueError:
                self.value_error('Dependency version spec range '
                                 'invalid: %s %s' % (dep_col, ver_spec))

            col_vers = models.CollectionVersion.objects.filter(collection=col)
            for v in [item.version for item in col_vers]:
                try:
                    if spec.match(semantic_version.Version(v)):
                        return
                except TypeError:
                    # semantic_version Spec('~1') is ok, but match throws error
                    pass

            self.value_error('Dependency found in galaxy but no matching '
                             'version found: %s %s' % (dep_col, ver_spec))

    def _check_tags_count(self):
        '''Checks tag count in metadata against max tags count constant'''
        tags = getattr(self, 'tags')
        if tags is not None and len(tags) > constants.MAX_TAGS_COUNT:
            self.value_error(
                'Expecting no more than %s tags in metadata' %
                constants.MAX_TAGS_COUNT)

    def __attrs_post_init__(self):
        '''Additional galaxy checks called post init'''
        super().__attrs_post_init__()
        self._check_required('readme')
        self._check_required('authors')
        self._check_dependencies()
        self._check_tags_count()
        for field in [
                        'description',
                        'repository',
                        'documentation',
                        'homepage',
                        'issues',
                     ]:
            self._check_non_null_str(field)


@attr.s(frozen=True)
class CollectionArtifactManifest(object):
    """Represents collection manifest metadata."""

    collection_info = attr.ib(type=GalaxyCollectionInfo)
    format = attr.ib(default=1)
    file_manifest_file = attr.ib(factory=dict)

    @classmethod
    def parse(cls, data):
        meta = json.loads(data)
        col_info = meta.pop('collection_info', None)
        meta['collection_info'] = GalaxyCollectionInfo(**col_info)
        return cls(**meta)


@attr.s(frozen=True)
class Collection(object):
    """Represents collection metadata and contents."""

    collection_info = attr.ib(type=GalaxyCollectionInfo)
    contents = attr.ib(factory=list)
    readme = attr.ib(default=None)
    quality_score = attr.ib(default=None)


# -----------------------------------------------------------------------------


class PlatformInfoSchema(mm.Schema):
    name = fields.Str()
    versions = fields.List(fields.Str())

    @mm.post_load
    def make_object(self, data):
        return PlatformInfo(**data)


class DependencyInfoSchema(mm.Schema):
    namespace = fields.Str()
    name = fields.Str()

    @mm.post_load
    def make_object(self, data):
        return DependencyInfo(**data)


class VideoLinkSchema(mm.Schema):
    url = fields.Str()
    description = fields.Str()

    @mm.post_load
    def make_object(self, data):
        return VideoLink(**data)


class ReadmeFileSchema(mm.Schema):
    """A schema for Readme class."""
    mimetype = fields.Str()
    raw = fields.Str()
    checksum = fields.Str()

    @mm.post_load
    def make_object(self, data):
        return readmeutils.ReadmeFile(**data)


class CommitInfoSchema(mm.Schema):
    """A schema for CommitInfo class."""
    sha = fields.Str(validate=validate.Length(equal=SHA1_LEN))
    author = fields.Str()
    author_email = fields.Str()
    author_date = fields.DateTime()
    committer = fields.Str()
    committer_email = fields.Str()
    committer_date = fields.DateTime()
    message = fields.Str()

    @mm.post_load
    def make_object(self, data):
        return git.CommitInfo(**data)


class RoleMetaSchema(mm.Schema):
    author = fields.Str()
    company = fields.Str()
    license = fields.Str()
    min_ansible_version = fields.Str(allow_none=True)
    min_ansible_container_version = fields.Str(allow_none=True)
    issue_tracker = fields.Str()
    github_branch = fields.Str()

    role_type = schema.Enum(constants.RoleType)
    tags = fields.List(fields.Str())
    platforms = fields.Nested(PlatformInfoSchema(), many=True)
    cloud_platforms = fields.List(fields.Str())
    dependencies = fields.Nested(DependencyInfoSchema(), many=True)
    video_links = fields.Nested(VideoLinkSchema(), many=True)


class ContentSchema(mm.Schema):
    """A schema for Content class."""
    name = fields.Str()
    original_name = fields.Str()
    path = fields.Str()
    content_type = schema.Enum(constants.ContentType)
    description = fields.Str()
    # Note(cutwater): This is workaround to make properly serializable
    # role metadata.
    role_meta = fields.Nested(RoleMetaSchema())
    readme = fields.Nested(ReadmeFileSchema())
    metadata = fields.Dict()

    @mm.post_load
    def make_object(self, data):
        return Content(**data)


class RepositorySchema(mm.Schema):
    """A schema for Repository class."""
    name = fields.Str()
    branch = fields.Str()
    commit = fields.Nested(CommitInfoSchema())
    format = schema.Enum(constants.RepositoryFormat)
    contents = fields.Nested(ContentSchema(), many=True)
    readme = fields.Nested(ReadmeFileSchema())

    @mm.post_load
    def make_object(self, data):
        return Repository(**data)
