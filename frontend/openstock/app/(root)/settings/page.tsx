import AnalysisSettingsWorkbench from "@/components/settings/AnalysisSettingsWorkbench";
import RiskRulesWorkbench from "@/components/settings/RiskRulesWorkbench";

export default function SettingsPage() {
    return <div className="settings-page-stack"><AnalysisSettingsWorkbench /><RiskRulesWorkbench /></div>;
}
