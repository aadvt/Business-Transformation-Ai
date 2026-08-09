import OperationsWorkspace from "@/components/OperationsWorkspace";

/* No PageHeader here on purpose: the shell's header already names this route,
   and the dashboard's subject is the live network itself. The focused vendor
   and its exposure float over the map instead. */
export default function WarRoomPage() {
  return <OperationsWorkspace />;
}
