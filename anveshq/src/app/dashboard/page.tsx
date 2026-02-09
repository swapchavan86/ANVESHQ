import { StockTable } from "@/components/features/StockTable";

export default function DashboardPage() {
  return (
    <div className="container mx-auto py-10">
      <h1 className="text-3xl font-bold mb-6">Momentum Dashboard</h1>
      <StockTable />
    </div>
  );
}
