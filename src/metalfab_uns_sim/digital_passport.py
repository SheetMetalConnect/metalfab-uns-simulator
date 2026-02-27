"""Digital Product Passport (DPP) implementation for Level 4.

Implements EU ESPR-compliant Digital Product Passports with:
- CO2 emissions tracking (material, energy, processing)
- Complete traceability (operations, machines, operators)
- Event notifications for external systems
- Certification and compliance data
- ESPR fields: unique identifier, data carrier, economic operator,
  product classification, substances of concern

Topic Structure:
    umh/v1/{enterprise}/{site}/_dpp/
      ├── passports/{dpp_id}/           # Individual passport data (retained)
      │   ├── metadata                  # Product info, customer, material, ESPR UID
      │   ├── carbon_footprint          # Detailed CO2 breakdown
      │   ├── traceability              # Operations history
      │   ├── certifications            # Quality, compliance, substances of concern
      │   └── summary                   # Dashboard view
      └── events/                       # Event stream (non-retained)
          ├── created                   # DPP created
          ├── operation                 # Operation completed
          ├── finalized                 # DPP finalized
          └── shipped                   # Product shipped

Reference: EU Ecodesign for Sustainable Products Regulation (ESPR) 2024/1781
"""

import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional


class DPPStatus(Enum):
    """Digital Product Passport lifecycle status."""
    CREATED = "CREATED"
    IN_PROGRESS = "IN_PROGRESS"
    QUALITY_CHECK = "QUALITY_CHECK"
    COMPLETED = "COMPLETED"
    SHIPPED = "SHIPPED"
    RECYCLED = "RECYCLED"


class DPPEventType(Enum):
    """DPP event types for external notifications."""
    CREATED = "DPP_CREATED"
    OPERATION_STARTED = "OPERATION_STARTED"
    OPERATION_COMPLETED = "OPERATION_COMPLETED"
    QUALITY_CHECKED = "QUALITY_CHECKED"
    FINALIZED = "DPP_FINALIZED"
    SHIPPED = "DPP_SHIPPED"


# =============================================================================
# ESPR-mandated dataclasses (EU 2024/1781 delegated acts for iron/steel)
# =============================================================================

@dataclass
class EconomicOperator:
    """ESPR Art. 9 - Economic operator responsible for the product."""
    company_name: str = "MetalFab BV"
    eori_number: str = "NL123456789000"  # EU customs identifier
    address: str = "Industrieweg 42, 5651 GK Eindhoven, Netherlands"
    authorized_representative: str = "Jan van den Berg"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "company_name": self.company_name,
            "eori_number": self.eori_number,
            "address": self.address,
            "authorized_representative": self.authorized_representative,
        }


@dataclass
class SubstanceOfConcern:
    """ESPR Art. 7(5)(b) - Substance of concern in the product."""
    substance_name: str
    cas_number: str  # Chemical Abstracts Service number
    concentration_pct: float
    location_in_product: str  # Where in the product the substance is found

    def to_dict(self) -> Dict[str, Any]:
        return {
            "substance_name": self.substance_name,
            "cas_number": self.cas_number,
            "concentration_pct": round(self.concentration_pct, 3),
            "location_in_product": self.location_in_product,
        }


@dataclass
class DataCarrier:
    """ESPR Art. 9(1) - Data carrier for accessing the DPP."""
    carrier_type: str = "QR"  # QR, NFC, RFID
    gs1_digital_link: str = ""  # GS1 Digital Link URL
    identifier: str = ""  # Machine-readable identifier

    def to_dict(self) -> Dict[str, Any]:
        return {
            "carrier_type": self.carrier_type,
            "gs1_digital_link": self.gs1_digital_link,
            "identifier": self.identifier,
        }


@dataclass
class ProductClassification:
    """Product classification codes for regulatory reporting."""
    prodcom_code: str = ""  # EU PRODCOM classification
    hs_code: str = ""  # Harmonized System (customs)
    cn_code: str = ""  # Combined Nomenclature (EU)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prodcom_code": self.prodcom_code,
            "hs_code": self.hs_code,
            "cn_code": self.cn_code,
        }


@dataclass
class OperationRecord:
    """Record of a single manufacturing operation."""

    operation_type: str  # "CUTTING", "BENDING", "WELDING", "COATING"
    machine_id: str
    machine_type: str
    operator_id: str
    operator_name: str

    # Timing
    started_at: str
    completed_at: str
    duration_minutes: float

    # Energy and emissions
    energy_kwh: float
    co2_kg: float  # Based on grid carbon intensity

    # Quality
    parts_produced: int
    parts_scrap: int
    quality_ok: bool = True

    # Process parameters (for traceability)
    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_type": self.operation_type,
            "machine_id": self.machine_id,
            "machine_type": self.machine_type,
            "operator_id": self.operator_id,
            "operator_name": self.operator_name,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_minutes": round(self.duration_minutes, 2),
            "energy_kwh": round(self.energy_kwh, 3),
            "co2_kg": round(self.co2_kg, 4),
            "parts_produced": self.parts_produced,
            "parts_scrap": self.parts_scrap,
            "quality_ok": self.quality_ok,
            "parameters": self.parameters,
        }


@dataclass
class QualityCheck:
    """Quality inspection record."""

    check_id: str
    inspector_id: str
    inspector_name: str
    timestamp: str
    check_type: str  # "DIMENSIONAL", "VISUAL", "FUNCTIONAL"
    passed: bool
    measurements: Dict[str, float] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "inspector_id": self.inspector_id,
            "inspector_name": self.inspector_name,
            "timestamp": self.timestamp,
            "check_type": self.check_type,
            "passed": self.passed,
            "measurements": self.measurements,
            "notes": self.notes,
        }


@dataclass
class MaterialInfo:
    """Material origin and properties."""

    material_code: str
    material_name: str
    material_type: str  # "STEEL", "STAINLESS", "ALUMINUM"
    thickness_mm: float
    weight_kg: float

    # Sustainability
    recycled_content_pct: float = 0.0
    recyclable: bool = True

    # Origin (for supply chain transparency)
    supplier: str = ""
    origin_country: str = ""
    batch_number: str = ""

    # Embodied carbon (kg CO2 per kg material)
    embodied_carbon_kg_per_kg: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "material_code": self.material_code,
            "material_name": self.material_name,
            "material_type": self.material_type,
            "thickness_mm": self.thickness_mm,
            "weight_kg": round(self.weight_kg, 3),
            "recycled_content_pct": round(self.recycled_content_pct, 1),
            "recyclable": self.recyclable,
            "supplier": self.supplier,
            "origin_country": self.origin_country,
            "batch_number": self.batch_number,
            "embodied_carbon_kg_per_kg": self.embodied_carbon_kg_per_kg,
        }


@dataclass
class CarbonFootprint:
    """Detailed CO2 emissions breakdown."""

    # Material phase
    material_co2_kg: float = 0.0  # Embodied carbon in raw material

    # Manufacturing phase
    cutting_co2_kg: float = 0.0
    forming_co2_kg: float = 0.0
    welding_co2_kg: float = 0.0
    coating_co2_kg: float = 0.0
    assembly_co2_kg: float = 0.0
    other_processing_co2_kg: float = 0.0

    # Logistics
    transport_co2_kg: float = 0.0

    # Total
    total_co2_kg: float = 0.0

    # Grid info (for transparency)
    grid_carbon_intensity_g_per_kwh: float = 0.0
    renewable_energy_pct: float = 0.0

    def calculate_total(self):
        """Calculate total CO2 emissions."""
        self.total_co2_kg = (
            self.material_co2_kg +
            self.cutting_co2_kg +
            self.forming_co2_kg +
            self.welding_co2_kg +
            self.coating_co2_kg +
            self.assembly_co2_kg +
            self.other_processing_co2_kg +
            self.transport_co2_kg
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_co2_kg": round(self.total_co2_kg, 4),
            "breakdown": {
                "material_co2_kg": round(self.material_co2_kg, 4),
                "manufacturing": {
                    "cutting_co2_kg": round(self.cutting_co2_kg, 4),
                    "forming_co2_kg": round(self.forming_co2_kg, 4),
                    "welding_co2_kg": round(self.welding_co2_kg, 4),
                    "coating_co2_kg": round(self.coating_co2_kg, 4),
                    "assembly_co2_kg": round(self.assembly_co2_kg, 4),
                    "other_co2_kg": round(self.other_processing_co2_kg, 4),
                },
                "transport_co2_kg": round(self.transport_co2_kg, 4),
            },
            "grid_info": {
                "carbon_intensity_g_per_kwh": round(self.grid_carbon_intensity_g_per_kwh, 1),
                "renewable_energy_pct": round(self.renewable_energy_pct, 1),
            },
            "co2_equivalent": {
                "trees_needed_to_offset": round(self.total_co2_kg / 0.021, 1),  # ~21kg CO2/tree/year
                "km_driven_equivalent": round(self.total_co2_kg / 0.12, 1),  # ~120g CO2/km avg car
            },
        }


@dataclass
class DigitalProductPassport:
    """Complete Digital Product Passport for a manufactured product.

    Complies with EU Digital Product Passport requirements:
    - Product identification and traceability
    - Environmental impact (CO2 emissions)
    - Material composition and origin
    - Manufacturing processes
    - Quality and certifications
    - Circularity information (recycling, repair)
    """

    # Unique identifier
    dpp_id: str

    # Product identity (required fields)
    job_id: str
    work_order: str
    product_name: str
    product_description: str
    customer: str
    quantity: int

    # Material
    material: MaterialInfo

    # Carbon footprint
    carbon_footprint: CarbonFootprint

    # ESPR unique identifier (GS1 SGTIN format)
    espr_uid: str = ""

    # ESPR: Data carrier (QR code / NFC)
    data_carrier: DataCarrier = field(default_factory=DataCarrier)

    # ESPR: Economic operator
    economic_operator: EconomicOperator = field(default_factory=EconomicOperator)

    # ESPR: Product classification
    product_classification: ProductClassification = field(default_factory=ProductClassification)

    # ESPR: Substances of concern
    substances_of_concern: List[SubstanceOfConcern] = field(default_factory=list)

    # Traceability
    operations: List[OperationRecord] = field(default_factory=list)
    quality_checks: List[QualityCheck] = field(default_factory=list)

    # Lifecycle
    status: DPPStatus = DPPStatus.CREATED
    created_at: str = ""
    finalized_at: Optional[str] = None

    # Facility info
    manufacturing_site: str = ""
    manufacturing_country: str = ""

    # Certifications (ISO, CE, etc.)
    certifications: List[str] = field(default_factory=list)

    # Circular economy
    recyclability_score: float = 0.0  # 0-100
    durability_score: float = 0.0  # 0-100 (ESPR Art. 7(2)(b))
    repairability_score: float = 0.0  # 0-100 (ESPR Art. 7(2)(b))
    repair_instructions_url: str = ""
    recycling_instructions: str = ""
    expected_lifetime_years: int = 0

    # Compliance
    reach_compliant: bool = True
    rohs_compliant: bool = True
    ce_marking: bool = True

    # Versioning
    dpp_version: str = "1.0.0"
    schema_version: str = "ESPR-2024-1781-v1"

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat() + "Z"

    def add_operation(self, operation: OperationRecord):
        """Add an operation record and update CO2 emissions."""
        self.operations.append(operation)

        # Update carbon footprint based on operation type
        op_type = operation.operation_type.upper()
        if "CUTTING" in op_type or "LASER" in op_type:
            self.carbon_footprint.cutting_co2_kg += operation.co2_kg
        elif "BENDING" in op_type or "FORMING" in op_type or "PRESS" in op_type:
            self.carbon_footprint.forming_co2_kg += operation.co2_kg
        elif "WELD" in op_type:
            self.carbon_footprint.welding_co2_kg += operation.co2_kg
        elif "COATING" in op_type or "PAINT" in op_type:
            self.carbon_footprint.coating_co2_kg += operation.co2_kg
        elif "ASSEMBLY" in op_type:
            self.carbon_footprint.assembly_co2_kg += operation.co2_kg
        else:
            self.carbon_footprint.other_processing_co2_kg += operation.co2_kg

        self.carbon_footprint.calculate_total()

    def add_quality_check(self, quality_check: QualityCheck):
        """Add a quality inspection record."""
        self.quality_checks.append(quality_check)

    def finalize(self):
        """Mark DPP as finalized (product complete)."""
        self.status = DPPStatus.COMPLETED
        self.finalized_at = datetime.now().isoformat() + "Z"
        self.carbon_footprint.calculate_total()

    def ship(self, transport_km: float = 0.0, transport_mode: str = "TRUCK"):
        """Mark as shipped and add transport emissions."""
        self.status = DPPStatus.SHIPPED

        # Calculate transport emissions (simplified)
        # Truck: ~62g CO2/ton-km, Rail: ~22g CO2/ton-km, Ship: ~8g CO2/ton-km
        emissions_per_ton_km = {
            "TRUCK": 0.062,
            "RAIL": 0.022,
            "SHIP": 0.008,
        }

        emission_factor = emissions_per_ton_km.get(transport_mode, 0.062)
        weight_tons = self.material.weight_kg / 1000
        self.carbon_footprint.transport_co2_kg = weight_tons * transport_km * emission_factor
        self.carbon_footprint.calculate_total()

    def to_metadata_dict(self) -> Dict[str, Any]:
        """Product metadata including ESPR-mandated fields."""
        return {
            "dpp_id": self.dpp_id,
            "espr_uid": self.espr_uid,
            "dpp_version": self.dpp_version,
            "schema_version": self.schema_version,
            "data_carrier": self.data_carrier.to_dict(),
            "economic_operator": self.economic_operator.to_dict(),
            "product": {
                "name": self.product_name,
                "description": self.product_description,
                "quantity": self.quantity,
                "classification": self.product_classification.to_dict(),
            },
            "customer": self.customer,
            "job_id": self.job_id,
            "work_order": self.work_order,
            "status": self.status.value,
            "created_at": self.created_at,
            "finalized_at": self.finalized_at,
            "manufacturing": {
                "site": self.manufacturing_site,
                "country": self.manufacturing_country,
            },
        }

    def to_traceability_dict(self) -> Dict[str, Any]:
        """Complete traceability data."""
        return {
            "dpp_id": self.dpp_id,
            "operations": [op.to_dict() for op in self.operations],
            "quality_checks": [qc.to_dict() for qc in self.quality_checks],
            "total_operations": len(self.operations),
            "total_quality_checks": len(self.quality_checks),
            "all_quality_passed": all(qc.passed for qc in self.quality_checks),
        }

    def to_certifications_dict(self) -> Dict[str, Any]:
        """Certifications, compliance, and ESPR substances of concern."""
        return {
            "dpp_id": self.dpp_id,
            "certifications": self.certifications,
            "compliance": {
                "reach_compliant": self.reach_compliant,
                "rohs_compliant": self.rohs_compliant,
                "ce_marking": self.ce_marking,
            },
            "substances_of_concern": [s.to_dict() for s in self.substances_of_concern],
            "circularity": {
                "recyclability_score": round(self.recyclability_score, 1),
                "durability_score": round(self.durability_score, 1),
                "repairability_score": round(self.repairability_score, 1),
                "expected_lifetime_years": self.expected_lifetime_years,
                "repair_instructions_url": self.repair_instructions_url,
                "recycling_instructions": self.recycling_instructions,
            },
        }

    def to_summary_dict(self) -> Dict[str, Any]:
        """Dashboard summary view."""
        return {
            "dpp_id": self.dpp_id,
            "espr_uid": self.espr_uid,
            "data_carrier_url": self.data_carrier.gs1_digital_link,
            "product_name": self.product_name,
            "customer": self.customer,
            "status": self.status.value,
            "quantity": self.quantity,
            "total_co2_kg": round(self.carbon_footprint.total_co2_kg, 4),
            "operations_count": len(self.operations),
            "quality_checks_passed": sum(1 for qc in self.quality_checks if qc.passed),
            "quality_checks_total": len(self.quality_checks),
            "created_at": self.created_at,
            "finalized_at": self.finalized_at,
        }


class DPPGenerator:
    """Generates realistic Digital Product Passports."""

    # Material data with embodied carbon (kg CO2 per kg material)
    MATERIALS = {
        "DC01": ("Cold Rolled Steel", "STEEL", 2.5, 30),  # embodied_carbon, recycled_content_pct
        "S235JR": ("Structural Steel", "STEEL", 2.8, 25),
        "S355": ("High Strength Steel", "STEEL", 3.0, 20),
        "AISI304": ("Stainless Steel 304", "STAINLESS", 6.5, 40),
        "AISI316L": ("Marine Grade Stainless", "STAINLESS", 7.0, 35),
        "AL5052": ("Aluminum Alloy 5052", "ALUMINUM", 9.0, 50),
        "AL6061": ("Aluminum 6061", "ALUMINUM", 10.0, 55),
    }

    SUPPLIERS = [
        ("Tata Steel", "NL"),
        ("ArcelorMittal", "BE"),
        ("ThyssenKrupp", "DE"),
        ("Outokumpu", "FI"),
        ("Salzgitter", "DE"),
        ("Voestalpine", "AT"),
    ]

    def __init__(self, grid_carbon_intensity: float = 350.0, renewable_pct: float = 30.0):
        """Initialize DPP generator.

        Args:
            grid_carbon_intensity: Grid carbon intensity in g CO2/kWh (default: EU average ~350)
            renewable_pct: Percentage of renewable energy in grid (default: EU ~30%)
        """
        self.grid_carbon_intensity = grid_carbon_intensity
        self.renewable_pct = renewable_pct

    def generate_material_info(self, material_code: str, thickness_mm: float, weight_kg: float) -> MaterialInfo:
        """Generate realistic material information."""
        if material_code not in self.MATERIALS:
            material_code = "DC01"

        mat_name, mat_type, embodied_carbon, recycled_pct = self.MATERIALS[material_code]
        supplier, origin = random.choice(self.SUPPLIERS)

        return MaterialInfo(
            material_code=material_code,
            material_name=mat_name,
            material_type=mat_type,
            thickness_mm=thickness_mm,
            weight_kg=weight_kg,
            recycled_content_pct=recycled_pct,
            recyclable=True,
            supplier=supplier,
            origin_country=origin,
            batch_number=f"BATCH-2025-{random.randint(1000, 9999)}",
            embodied_carbon_kg_per_kg=embodied_carbon,
        )

    # PRODCOM/HS code lookup by material type
    PRODUCT_CLASSIFICATIONS = {
        "STEEL": ProductClassification(
            prodcom_code="24.10.31",  # Flat-rolled products of iron/steel
            hs_code="7208",  # Flat-rolled iron/steel >=600mm wide, hot-rolled
            cn_code="7208 51 00",
        ),
        "STAINLESS": ProductClassification(
            prodcom_code="24.10.61",  # Flat-rolled products of stainless steel
            hs_code="7219",  # Flat-rolled stainless steel >=600mm wide
            cn_code="7219 33 00",
        ),
        "ALUMINUM": ProductClassification(
            prodcom_code="24.42.11",  # Aluminum bars, rods, profiles
            hs_code="7606",  # Aluminum plates, sheets, strip >0.2mm
            cn_code="7606 12 00",
        ),
    }

    # Substances of concern by material type (ESPR Art. 7(5)(b))
    SUBSTANCES_BY_MATERIAL = {
        "STEEL": [
            SubstanceOfConcern("Lead", "7439-92-1", 0.003, "Base material trace element"),
        ],
        "STAINLESS": [
            SubstanceOfConcern("Nickel", "7440-02-0", 8.0, "Alloy component (austenite stabilizer)"),
            SubstanceOfConcern("Chromium", "7440-47-3", 18.0, "Alloy component (corrosion resistance)"),
        ],
        "ALUMINUM": [
            SubstanceOfConcern("Lead", "7439-92-1", 0.001, "Base material trace element"),
        ],
    }

    def _generate_espr_uid(self) -> str:
        """Generate GS1 SGTIN-format unique identifier for ESPR compliance."""
        # GS1 Company Prefix (MetalFab BV) + Item Reference + Serial
        company_prefix = "8712345"  # Fictional NL GS1 prefix
        item_ref = f"{random.randint(10000, 99999)}"
        serial = f"{random.randint(100000000, 999999999)}"
        return f"urn:epc:id:sgtin:{company_prefix}.{item_ref}.{serial}"

    def _generate_data_carrier(self, espr_uid: str) -> DataCarrier:
        """Generate data carrier with GS1 Digital Link URL."""
        # Extract serial from SGTIN for URL
        parts = espr_uid.split(".")
        serial = parts[-1] if len(parts) >= 3 else str(random.randint(100000, 999999))
        gtin = f"08712345{random.randint(10000, 99999):05d}"

        return DataCarrier(
            carrier_type="QR",
            gs1_digital_link=f"https://id.metalfab.eu/01/{gtin}/21/{serial}",
            identifier=gtin,
        )

    def _generate_substances_of_concern(self, material_type: str) -> List[SubstanceOfConcern]:
        """Generate material-type-aware substances of concern list."""
        return list(self.SUBSTANCES_BY_MATERIAL.get(material_type, []))

    def _generate_product_classification(self, material_type: str) -> ProductClassification:
        """Generate PRODCOM/HS classification based on material type."""
        return self.PRODUCT_CLASSIFICATIONS.get(
            material_type,
            ProductClassification(prodcom_code="24.10.31", hs_code="7208", cn_code="7208 51 00"),
        )

    def create_dpp_for_job(self, job_id: str, work_order: str, product_name: str,
                          customer: str, material_code: str, thickness_mm: float,
                          quantity: int, site: str, country: str) -> DigitalProductPassport:
        """Create a new ESPR-compliant DPP for a manufacturing job."""

        dpp_id = f"DPP-{datetime.now().strftime('%Y%m%d')}-{random.randint(10000, 99999)}"

        # Estimate weight (simplified: 1m² sheet @ thickness)
        weight_kg = 1.0 * thickness_mm * 7.85 / 1000 * quantity  # Steel density approximation

        material_info = self.generate_material_info(material_code, thickness_mm, weight_kg)

        # Initialize carbon footprint with material embodied carbon
        carbon_fp = CarbonFootprint(
            material_co2_kg=material_info.weight_kg * material_info.embodied_carbon_kg_per_kg,
            grid_carbon_intensity_g_per_kwh=self.grid_carbon_intensity,
            renewable_energy_pct=self.renewable_pct,
        )
        carbon_fp.calculate_total()

        # ESPR fields
        espr_uid = self._generate_espr_uid()
        data_carrier = self._generate_data_carrier(espr_uid)
        product_classification = self._generate_product_classification(material_info.material_type)
        substances = self._generate_substances_of_concern(material_info.material_type)

        dpp = DigitalProductPassport(
            dpp_id=dpp_id,
            espr_uid=espr_uid,
            job_id=job_id,
            work_order=work_order,
            product_name=product_name,
            product_description=f"{material_code} {thickness_mm}mm - {product_name}",
            customer=customer,
            quantity=quantity,
            material=material_info,
            carbon_footprint=carbon_fp,
            data_carrier=data_carrier,
            economic_operator=EconomicOperator(),
            product_classification=product_classification,
            substances_of_concern=substances,
            manufacturing_site=site,
            manufacturing_country=country,
            certifications=["ISO 9001:2015", "ISO 14001:2015"],
            recyclability_score=random.uniform(85, 98),
            durability_score=random.uniform(70, 95),
            repairability_score=random.uniform(40, 75),
            expected_lifetime_years=random.randint(10, 25),
            recycling_instructions="Steel: 100% recyclable. Return to metal recycler.",
            reach_compliant=True,
            rohs_compliant=True,
            ce_marking=True,
        )

        return dpp

    def create_operation_record(self, operation_type: str, machine_id: str, machine_type: str,
                                operator_id: str, operator_name: str, duration_minutes: float,
                                energy_kwh: float, parts_produced: int = 1,
                                parts_scrap: int = 0) -> OperationRecord:
        """Create an operation record with CO2 calculation."""

        # Calculate CO2 from energy consumption
        co2_kg = (energy_kwh * self.grid_carbon_intensity) / 1000  # g to kg

        now = datetime.now()
        started = now - timedelta(minutes=duration_minutes)

        # Generate realistic process parameters based on operation type
        parameters = {}
        if "LASER" in machine_type.upper() or "CUTTING" in operation_type.upper():
            parameters = {
                "laser_power_w": random.randint(3000, 6000),
                "cutting_speed_mm_min": random.randint(2000, 5000),
                "assist_gas": random.choice(["N2", "O2"]),
                "focal_length_mm": random.uniform(5.0, 10.0),
            }
        elif "PRESS" in machine_type.upper() or "BENDING" in operation_type.upper():
            parameters = {
                "tonnage": random.randint(80, 320),
                "bend_angle_deg": random.uniform(30, 150),
                "back_gauge_mm": random.uniform(50, 500),
            }
        elif "WELD" in operation_type.upper():
            parameters = {
                "current_a": random.randint(150, 300),
                "voltage_v": random.uniform(20, 35),
                "wire_feed_m_min": random.uniform(5, 15),
                "gas_flow_l_min": random.uniform(12, 20),
            }

        return OperationRecord(
            operation_type=operation_type,
            machine_id=machine_id,
            machine_type=machine_type,
            operator_id=operator_id,
            operator_name=operator_name,
            started_at=started.isoformat() + "Z",
            completed_at=now.isoformat() + "Z",
            duration_minutes=duration_minutes,
            energy_kwh=energy_kwh,
            co2_kg=co2_kg,
            parts_produced=parts_produced,
            parts_scrap=parts_scrap,
            quality_ok=parts_scrap == 0,
            parameters=parameters,
        )

    def create_quality_check(self, check_type: str = "DIMENSIONAL") -> QualityCheck:
        """Create a quality inspection record."""

        inspector_id = f"QC_{random.randint(100, 999)}"
        inspectors = ["Anna Schmidt", "Peter Jansen", "Maria Ionescu", "Jan de Vries"]

        passed = random.random() > 0.05  # 95% pass rate

        measurements = {}
        notes = ""

        if check_type == "DIMENSIONAL":
            measurements = {
                "length_mm": round(random.uniform(99.8, 100.2), 2),
                "width_mm": round(random.uniform(49.9, 50.1), 2),
                "thickness_mm": round(random.uniform(1.98, 2.02), 2),
                "tolerance_ok": passed,
            }
            notes = "Within tolerance" if passed else "Out of tolerance - rework needed"
        elif check_type == "VISUAL":
            measurements = {
                "surface_quality": "GOOD" if passed else "FAIR",
                "scratches": random.randint(0, 2),
                "dents": random.randint(0, 1),
            }
            notes = "Surface acceptable" if passed else "Minor surface defects"

        return QualityCheck(
            check_id=f"QC-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}",
            inspector_id=inspector_id,
            inspector_name=random.choice(inspectors),
            timestamp=datetime.now().isoformat() + "Z",
            check_type=check_type,
            passed=passed,
            measurements=measurements,
            notes=notes,
        )
