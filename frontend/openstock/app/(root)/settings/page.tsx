import AnalysisSettingsWorkbench from "@/components/settings/AnalysisSettingsWorkbench";
import InvestmentPolicyWorkbench from "@/components/settings/InvestmentPolicyWorkbench";
import RiskRulesWorkbench from "@/components/settings/RiskRulesWorkbench";

export default function SettingsPage() {
    return <div className="settings-page-stack"><AnalysisSettingsWorkbench /><InvestmentPolicyWorkbench /><RiskRulesWorkbench /></div>;
}
