/*
 * roleAddController.js
 *
 * (c) 2012-2015, Ansible, Inc.
 *
 */


'use strict';

(function(angular) {
    
    var mod = angular.module('roleAddController', []);

    mod.controller('RoleAddCtrl', [
        '$scope',
        '$interval',
        '$timeout',
        '$analytics',
        '$q',
        'githubRepoService',
        'currentUserService',
        'importService',
        'roleService',
        'repositories',
        'notificationSecretService',
        _controller
    ]);

    function _controller(
        $scope,
        $interval,
        $timeout,
        $analytics,
        $q,
        githubRepoService,
        currentUserService,
        importService,
        roleService,
        repositories,
        notificationSecretService) {

        
        $scope.page_title = 'My Roles';
        $scope.loading = true;
        $scope.repositories = repositories;
        $scope.username = currentUserService.username;
        $scope.toggleRepository = _toggleRepository;
        $scope.refreshing = false;
        $scope.refreshRepos = _refresh;
        $scope.showIntegrations = _showIntegrations;
        $scope.cancelIntegrations = _cancelIntegrations;
        $scope.revealGithub = _revealGithub;
        $scope.revealTravis = _revealTravis;
        $scope.clearTravis = _clearTravis;
        $scope.clearGithub = _clearGithub;
        $scope.updateSettings = _updateSettings;
        $scope.reimport = _importRepository;
        $scope.github_auth = true;

        if (!(currentUserService.authenticated && currentUserService.connected_to_github)) {
            $scope.github_auth = false;
            $scope.loading = false;
            return;
        }
        
        if (currentUserService.cache_refreshed) {
            $scope.loading = false;
            _setup();
        } else {
            _waitForRefresh();
        }

        return;

        
        function _waitForRefresh() {
            var stop = $interval(function() {
                currentUserService.update().then(function(userData) {
                    if (userData.cache_refreshed) {
                        _kill();
                    }
                });
            }, 5000);

            function _kill() {
                $interval.cancel(stop);
                if ($scope.repositories.length == 0) {
                    githubRepoService.get().$promise.then(function(response) {
                        $scope.loading = false;
                        $scope.repositories = response.results;
                        _setup();
                    });
                } else {
                    $scope.loading = false;
                    _setup();
                }
            }
        }

        function _setup() {
            $scope.repositories.forEach(function(repo) {
                repo.github_secret_type = "password";
                repo.travis_token_type = "password";
                if (repo.summary_fields) {
                    repo.summary_fields.notification_secrets.forEach(function(secret) {
                        if (secret.source == 'travis') {
                            repo.travis_id = secret.id;
                            repo.travis_token = secret.secret;
                        } else {
                            repo.github_id = secret.id;
                            repo.github_secret = secret.secret;
                        }
                    });
                }
                if (repo.summary_fields && repo.summary_fields.roles.length) {
                    repo.role_id = repo.summary_fields.roles[0].id;
                    repo.role_name = repo.summary_fields.roles[0].name;
                    repo.role_namespace = repo.summary_fields.roles[0].namespace;
                    repo.master_role_name = repo.role_name;
                } else {
                    var new_name;
                    if (repo.github_repo === 'ansible') {
                        new_name = repo.github_repo;
                    } else {
                        repo.github_repo.replace(/^(ansible[-_+.]*)*(role[-_+.]*)*/g, function(match, p1, p2, offset, str) {
                            var result = str;
                            if (p1) {
                                result = result.replace(new RegExp(p1,'g'), '');
                            }
                            if (p2) {
                                result = result.replace(new RegExp(p2,'g'), '');
                            }
                            result = result.replace(/^-/,'');
                            new_name = result;
                        });
                        if (!new_name) {
                            new_name = repo.github_repo;
                        }
                    }
                    repo.role_name = new_name;
                    repo.master_role_name = repo.role_name;
                }
            });
        }

        function _showIntegrations(_repo) {
            _repo.show_integrations = !_repo.show_integrations; 
            _repo.github_secret_type = "password";
            _repo.travis_token_type = "password";
            if (_repo.show_integrations) {
                // reveal the form. keep a copy in case user clicks cancel.
                $scope.master = {
                    travis_id: _repo.travis_id,
                    travis_token: _repo.travis_token,
                    github_id: _repo.github_id,
                    github_secret: _repo.github_secret
                };
            }
        }

        function _cancelIntegrations(_repo) {
            _repo.role_name = _repo.master_role_name
            _repo.travis_id = $scope.master.travis_id;
            _repo.travis_token = $scope.master.travis_token;
            _repo.github_id = $scope.master.github_id;
            _repo.github_secret = $scope.github_secret;
            _repo.show_integrations = !_repo.show_integrations; 
        }

        function _revealGithub(_repo) {
            _repo.github_secret_type = (_repo.github_secret_type == 'password') ? 'text' : 'password';
        }

        function _revealTravis(_repo) {
            _repo.travis_token_type = (_repo.travis_token_type == 'password') ? 'text' : 'password';
        }

        function _clearTravis(_repo) {
            _repo.travis_token = null;
        }

        function _clearGithub(_repo) {
            _repo.github_secret = null;
        }

        function _updateSettings(_repo) {
            _repo.show_integrations = false;
            _updateRoleName(_repo).then(function() {
                _updateSecrets(_repo);
            });
        }

        function _updateRoleName(_repo) {
            var deferred = $q.defer();
            if (_repo.master_role_name !== _repo.role_name) {
                _repo.is_enabled = true;
                _repo.state = 'PENDING';
                _repo.master_role_name = _repo.role_name;
                importService.imports.save({
                    'github_user': _repo.github_user,
                    'github_repo': _repo.github_repo,
                    'alternate_role_name': _repo.role_name
                }).$promise.then(function(data) {
                    _checkStatus(data, deferred);
                });
            } else {
                $timeout(function() {
                    deferred.resolve();
                }, 300);
            }
            return deferred.promise;
        }

        function _updateSecrets(_repo) {
            // deleted secret
            if (_repo.travis_id && !_repo.travis_token) {
                $analytics.eventTrack('remove_travis', {
                    category: _repo.github_user + '/' + _repo.github_repo
                });
                notificationSecretService.delete({id: _repo.travis_id}).$promise.then(function(repsonse) {
                    _repo.travis_id = null;
                });
            }
            // changed secret
            if (_repo.travis_id && _repo.travis_token && !/^\*{6}/.test(_repo.travis_token)) {
                $analytics.eventTrack('change_travis', {
                    category: _repo.github_user + '/' + _repo.github_repo
                });
                notificationSecretService.put({
                    id: _repo.travis_id,
                    source: 'travis',
                    github_user: _repo.github_user,
                    github_repo: _repo.github_repo,
                    secret: _repo.travis_token
                }).$promise.then(function(response) {
                    _repo.travis_token = response.secret;
                });
            }
            // new secret
            if (!_repo.travis_id && _repo.travis_token && !/^\*{6}/.test(_repo.travis_token)) {
                $analytics.eventTrack('add_travis', {
                    category: _repo.github_user + '/' + _repo.github_repo
                });
                notificationSecretService.save({
                    source: 'travis',
                    github_user: _repo.github_user,
                    github_repo: _repo.github_repo,
                    secret: _repo.travis_token
                }).$promise.then(function(response) {
                    _repo.travis_id = response.id;
                    _repo.travis_token = response.secret;
                });
            }
        }
        
        function _refresh() {
            $scope.refreshing = true;
            githubRepoService.refresh().$promise.then(function(response) {
                $scope.repositories = response;
                _setup();
                $scope.refreshing = false;
                $timeout(function() {
                    $scope.$apply();
                },300);
            });
        }

        function _importRepository(_repo) {
            if (_repo.is_enabled) {
                _repo.state = 'PENDING';
                importService.imports.save({
                    'github_user': _repo.github_user,
                    'github_repo': _repo.github_repo,
                    'alternate_role_name': _repo.role_name
                }).$promise.then(_checkStatus);
            }
        }

        function _toggleRepository(_repo) {
            if (_repo.is_enabled) {
                _importRepository(_repo);
            } else {
                roleService.delete({
                    'github_user': _repo.github_user,
                    'github_repo': _repo.github_repo
                }).$promise.then(function(response) {
                    $scope.repositories.forEach(function(repo) {
                        response.deleted_roles.forEach(function(deleted) {
                            if (deleted.github_user === repo.github_user && deleted.github_repo === _repo.github_repo) {
                                repo.state = null;
                            }
                        });
                    });
                });
            }
        }

        function _checkStatus(response, deferred) {
            var stop = $interval(function(_id) {
                importService.imports.query({ id: _id}).$promise.then(function(response) {
                    $scope.repositories.every(function(repo) {
                        if (repo.github_user == response.results[0].github_user && 
                            repo.github_repo === response.results[0].github_repo) {
                            repo.state = response.results[0].state;
                            repo.role_id = response.results[0].role;
                            return false;
                        }
                        return true;
                    });
                    if (response.results[0].state == 'SUCCESS' || response.results[0].state == 'FAILED') {
                        _kill();
                    }
                });
            }, 5000, 0, false, response.results[0].id)

            function _kill() {
                $interval.cancel(stop);
                if (deferred) {
                    deferred.resolve();
                }
            }
        }
    }

})(angular);
 

