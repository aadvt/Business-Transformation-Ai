import PageHeader from "@/components/PageHeader";
import OperationsWorkspace from "@/components/OperationsWorkspace";

export default function WarRoomPage() {
  return (
    <div>
      <PageHeader
        title="Operations network"
        subtitle="Track delivery health, investigate disruptions, and ingest supply data from one workspace."
      />
      <OperationsWorkspace />
    </div>
  );
}
