// Exposes handlers to the page's inline onclick attributes and starts the app
'use strict';

window.submitMaterial = submitMaterial;
window.submitPR = submitPR;
window.addPRLineRow = addPRLineRow;
window.removePRLineRow = removePRLineRow;
window.onPRLineSKUSelect = onPRLineSKUSelect;
window.onPRLineFieldChange = onPRLineFieldChange;
window.submitSupplier = submitSupplier;
window.submitPO = submitPO;
window.promptDelete = promptDelete;
window.viewMaterialDetail = viewMaterialDetail;
window.openApprovalModal = openApprovalModal;
window.handleDecisionChange = handleDecisionChange;
window.showUnauthorizedStep2Notice = showUnauthorizedStep2Notice;
window.submitPRApproval = submitPRApproval;
window.openRevisePRModal = openRevisePRModal;
window.onRevisionItemChange = onRevisionItemChange;
window.submitPRRevision = submitPRRevision;
window.viewPRVoucher = viewPRVoucher;
window.convertPRToPO = convertPRToPO;
window.handleLoginSubmit = handleLoginSubmit;
window.handleLogout = handleLogout;
window.toggleUserStatus = toggleUserStatus;
window.handleCreateUser = handleCreateUser;
window.changeUserPassword = changeUserPassword;
window.forceSyncAllToCloud = forceSyncAllToCloud;
window.setPRFilter = setPRFilter;
window.setPRSort = setPRSort;

window.addEventListener('DOMContentLoaded', () => {
  currentUser = null;
  runCalculator();

  const nextWeek = new Date();
  nextWeek.setDate(nextWeek.getDate() + 7);
  const poDue = document.getElementById('po-due');
  const prDue = document.getElementById('pr-due-date');
  const revDue = document.getElementById('revise-due-date');
  if (poDue) poDue.value = nextWeek.toISOString().split('T')[0];
  if (prDue) prDue.value = nextWeek.toISOString().split('T')[0];
  if (revDue) revDue.value = nextWeek.toISOString().split('T')[0];

  renderMaterials(materialsData);
  renderPRs();
  renderSuppliers();
  renderPipeline();
  renderSOP();
  updateHeaderKPIs();
  applyUserProfileUI();

  lucide.createIcons();
  initCloudBackend();
});
