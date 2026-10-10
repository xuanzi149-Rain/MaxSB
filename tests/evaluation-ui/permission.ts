export const hasPermission = () => new URLSearchParams(location.search).get('state') !== 'readonly'
const value = { getApplicationWorkspaceResourcePermission: () => '', getWorkspacePermissionWorkspaceManageRole: () => '', getWorkspaceRole: () => '' }
export const PermissionConst = { APPLICATION_EDIT: value }
export const RoleConst = { WORKSPACE_MANAGE: value, ADMIN: '' }
