import { cn } from '@/lib/utils';

interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: React.ReactNode;
  trend?: { value: number; label: string };
  color?: 'blue' | 'green' | 'yellow' | 'purple' | 'orange';
}

const colorMap = {
  blue:   'bg-blue-500/10   text-blue-400   ring-1 ring-blue-500/20',
  green:  'bg-green-500/10  text-green-400  ring-1 ring-green-500/20',
  yellow: 'bg-yellow-500/10 text-yellow-400 ring-1 ring-yellow-500/20',
  purple: 'bg-purple-500/10 text-purple-400 ring-1 ring-purple-500/20',
  orange: 'bg-orange-500/10 text-orange-400 ring-1 ring-orange-500/20',
};

export function StatCard({ title, value, subtitle, icon, trend, color = 'blue' }: StatCardProps) {
  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-5 hover:border-gray-700 transition-colors">
      <div className="flex items-start justify-between mb-3">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">{title}</p>
        {icon && (
          <div className={cn('w-9 h-9 rounded-lg flex items-center justify-center shrink-0', colorMap[color])}>
            {icon}
          </div>
        )}
      </div>
      <p className="text-2xl font-bold text-white mb-1">{value}</p>
      {subtitle && <p className="text-xs text-gray-500">{subtitle}</p>}
      {trend && (
        <p className={cn('text-xs mt-1 font-medium', trend.value >= 0 ? 'text-green-400' : 'text-red-400')}>
          {trend.value >= 0 ? '↑' : '↓'} {Math.abs(trend.value)} {trend.label}
        </p>
      )}
    </div>
  );
}
