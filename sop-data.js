// Static content of the SOP tab
'use strict';

const sopData = [
  {
    id: "FORM-01",
    title: "Purchase Requisition (PR)",
    type: "Standard Form",
    role: "Production / Sales",
    desc: "Captures project BOM requirement, stock balance, and needed fabrication date before purchasing.",
    fields: "PR No, Item Code, Detailed Spec, Quantity, Required Date, Approved Signatures"
  },
  {
    id: "FORM-02",
    title: "RFQ & Landed Cost Analysis",
    type: "Evaluation Sheet",
    role: "Purchasing Officer",
    desc: "Compares 3 vendor bids calculating freight, discounts, handling, and Net Landed Cost per unit.",
    fields: "Supplier IDs, Base Price, Discount %, Shipping Cost, Duties, Net Landed Unit Cost"
  },
  {
    id: "FORM-03",
    title: "Official Purchase Order (PO)",
    type: "Legal Contract",
    role: "Purchasing Manager",
    desc: "Binding procurement order with precise tolerances, delivery dates, packing rules, and penalty terms.",
    fields: "PO ID, Full Spec Codes, Unit Rate, Total Value, Payment Term, Financial Approval"
  },
  {
    id: "FORM-04",
    title: "Goods Receiving Note (GRN)",
    type: "Warehouse Gate",
    role: "Warehouse Inward",
    desc: "Logs actual count, carton condition, and physical receipts at the dock prior to ERP entry.",
    fields: "GRN No, PO No, Vendor Delivery Slip, Received Qty, Damaged Units, Receiver Sign"
  },
  {
    id: "FORM-05",
    title: "QC Non-Conformance & RMA",
    type: "Quality Gate",
    role: "QC Inspection",
    desc: "Quarantines defective profiles or scratched glass and initiates vendor claims for credit notes.",
    fields: "Defect Description, Photos, Discrepant Qty, Disposition (Scrap/Return/Credit)"
  },
  {
    id: "SOP-MATCH",
    title: "3-Way Match & Disbursement",
    type: "Finance SOP",
    role: "Accounts Payable",
    desc: "Reconciles PO Rate = GRN Accepted Qty = Invoice Amount. Zero payments without verified match.",
    fields: "Matched PO, Signed GRN, Verified Tax Invoice, Payment Voucher ID"
  }
];
