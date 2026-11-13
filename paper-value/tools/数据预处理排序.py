import pandas as pd
import re
import os
import time
import warnings

warnings.filterwarnings('ignore')
os.chdir(f'{os.path.dirname(os.path.abspath(__file__))}')

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

class DataPreprocessor:
    """数据预处理排序器"""
    
    def __init__(self, csv_file_path, 
                 time_columns=['year', 'volume', 'issue'],
                 info_columns=['journal', 'author'],
                 unique_id_column='paper_id',
                 text_column=None,
                 analyze_info_columns=True):
        """
        初始化预处理器
        
        Args:
            csv_file_path (str): CSV文件路径
            time_columns (list): 时间列列表，按优先级顺序排列
            info_columns (list): 信息列列表
            unique_id_column (str): 唯一号列名
            text_column (str or None): 文本内容列名
            analyze_info_columns (bool): 是否分析信息列
        """
        self.csv_file_path = csv_file_path
        self.time_columns = time_columns
        self.info_columns = info_columns
        self.unique_id_column = unique_id_column
        self.text_column = text_column
        self.analyze_info_columns = analyze_info_columns
        self.df = None
        
        self.analysis_mode = 'info_columns' if (self.analyze_info_columns or self.text_column is None) else 'text_column'
    
    def _extract_year_robustly(self, value_series):
        """健壮的年份提取"""
        def extract_single_year(val):
            if pd.isna(val):
                return pd.NA
            
            if isinstance(val, (int, float)) and not pd.isna(val):
                year = int(val)
                if 1900 <= year <= 2100:
                    return year
            
            val_str = str(val).upper().strip()
            val_str = val_str.replace('O', '0').replace('I', '1').replace('L', '1')
            
            match = re.search(r'(\d{4})', val_str)
            if match:
                year = int(match.group(1))
                if 1900 <= year <= 2100:
                    return year
            
            match = re.search(r'(\d{3})', val_str)
            if match:
                year_prefix = match.group(1)
                if year_prefix.startswith('19') or year_prefix.startswith('20'):
                    return int(year_prefix + '0')
            
            return pd.NA
        
        return value_series.apply(extract_single_year)
    
    def load_and_sort_data(self):
        """加载数据并排序"""
        print("=" * 70)
        print("📝 数据预处理排序器")
        print("=" * 70)
        print("正在加载数据...")
        
        try:
            self.df = pd.read_csv(self.csv_file_path)
            print(f"数据加载成功，共 {len(self.df):,} 条记录")
            
            required_columns = self.time_columns + self.info_columns + [self.unique_id_column]
            if self.text_column and self.analysis_mode == 'text_column':
                required_columns.append(self.text_column)
                
            missing_columns = [col for col in required_columns if col not in self.df.columns]
            if missing_columns:
                print(f"❌ 错误：缺少必要的列：{missing_columns}")
                print(f"现有列：{list(self.df.columns)}")
                return False
            
            print("正在预处理数据...")
            
            for i, col in enumerate(self.time_columns):
                original_count = self.df[col].notna().sum()
                
                numeric_converted = pd.to_numeric(self.df[col], errors='coerce')
                
                if i == 0:
                    non_numeric_mask = numeric_converted.isna() & self.df[col].notna()
                    if non_numeric_mask.any():
                        print(f"⚠️  发现 {non_numeric_mask.sum()} 个非标准{col}格式，使用智能提取...")
                        extracted_years = self._extract_year_robustly(self.df.loc[non_numeric_mask, col])
                        numeric_converted.loc[non_numeric_mask] = extracted_years
                    
                    numeric_converted = numeric_converted.round()
                    self.df[col] = numeric_converted.astype('Int64')
                else:
                    numeric_converted = numeric_converted.fillna(0).round()
                    self.df[col] = numeric_converted.astype('Int64')
                
                processed_count = self.df[col].notna().sum()
                if processed_count != original_count:
                    print(f"   {col}列：{original_count:,} -> {processed_count:,} 条有效记录")
            
            initial_count = len(self.df)
            
            self.df = self.df.dropna(subset=[self.unique_id_column])
            self.df = self.df[self.df[self.unique_id_column].astype(str).str.strip() != '']
            
            self.df = self.df.dropna(subset=[self.time_columns[0]])
            
            if self.analysis_mode == 'info_columns':
                info_not_null = self.df[self.info_columns].notna().any(axis=1)
                self.df = self.df[info_not_null]
            else:
                self.df = self.df.dropna(subset=[self.text_column])
                self.df = self.df[self.df[self.text_column].astype(str).str.strip() != '']
            
            print(f"数据清理：{initial_count:,} -> {len(self.df):,} 条记录")
            
            unique_ids = self.df[self.unique_id_column].nunique()
            if unique_ids != len(self.df):
                print(f"⚠️  发现重复唯一号，去重后保留：{unique_ids:,} 条记录")
                self.df = self.df.drop_duplicates(subset=[self.unique_id_column], keep='first')
            
            print(f"正在排序：{' > '.join(self.time_columns)}")
            sort_ascending = [True] * len(self.time_columns)
            self.df = self.df.sort_values(self.time_columns, ascending=sort_ascending)
            print("✅ 排序完成")
            
            for col in self.time_columns:
                try:
                    col_values = pd.to_numeric(self.df[col], errors='coerce').dropna()
                    if len(col_values) > 0:
                        col_min = col_values.min()
                        col_max = col_values.max()
                        if pd.notna(col_min) and pd.notna(col_max):
                            if col_min == col_max:
                                print(f"   {col}：{int(col_min)}")
                            else:
                                print(f"   {col}：{int(col_min)} - {int(col_max)}")
                        else:
                            print(f"   {col}：数据包含无效值")
                    else:
                        print(f"   {col}：无有效数据")
                except Exception as e:
                    print(f"   {col}：无法显示范围（{e}）")
            
            if self.analysis_mode == 'info_columns':
                print("正在预合并分析列...")
                self.df['combined_info'] = self.df[self.info_columns].fillna('').agg(' '.join, axis=1)
                print("✅ 预合并分析列完成")
            
            return True
            
        except FileNotFoundError:
            print(f"❌ 错误：文件 '{self.csv_file_path}' 不存在")
            return False
        except Exception as e:
            print(f"❌ 数据加载错误：{e}")
            return False
    
    def save_sorted_data(self):
        """保存排序后的数据"""
        if self.df is None:
            print("❌ 错误：没有数据可保存")
            return False
        
        output_file = self.csv_file_path + '.sorted_temp.csv'
        
        print(f"\n📝 保存排序数据到：{output_file}")
        print(f"   数据规模：{len(self.df):,} 行 × {len(self.df.columns)} 列")
        print(f"   预计耗时：约 {len(self.df) // 30000} 秒")
        print(f"   💡 大文件保存需要时间，请耐心等待...")
        
        try:
            save_start = time.time()
            self.df.to_csv(output_file, index=False, encoding='utf-8')
            save_time = time.time() - save_start
            file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
            print(f"✅ 保存完成！")
            print(f"   文件大小：{file_size_mb:.1f} MB")
            print(f"   耗时：{save_time:.1f} 秒")
            print(f"   平均速度：{len(self.df) / save_time:.0f} 条/秒")
            return True
        except MemoryError as e:
            print(f"❌ 内存不足错误：{e}")
            print(f"   建议：关闭其他程序释放内存")
            return False
        except OSError as e:
            print(f"❌ 磁盘写入错误：{e}")
            print(f"   建议：检查磁盘空间和文件权限")
            return False
        except Exception as e:
            print(f"❌ 保存失败：{e}")
            return False
    
    def run(self):
        """运行完整预处理流程"""
        start_time = time.time()
        
        if not self.load_and_sort_data():
            return False
        
        if not self.save_sorted_data():
            return False
        
        total_time = time.time() - start_time
        
        print("\n" + "=" * 70)
        print("✅ 预处理完成！")
        print(f"⏱️  总耗时：{total_time:.2f} 秒")
        print(f"📄 中间文件已生成，可供主程序重复使用")
        print("=" * 70)
        return True


if __name__ == "__main__":
    CSV_FILE_PATH = '2025外文论文全字段.csv'
    TIME_COLUMNS = ['出版年', '卷', '期']
    INFO_COLUMNS = ['期刊名称', '标题', '关键词', 'KeywordsPlus', '摘要']
    UNIQUE_ID_COLUMN = '入藏号'
    
    try:
        preprocessor = DataPreprocessor(
            csv_file_path=CSV_FILE_PATH,
            time_columns=TIME_COLUMNS,
            info_columns=INFO_COLUMNS,
            unique_id_column=UNIQUE_ID_COLUMN,
            text_column=None,
            analyze_info_columns=True
        )
        
        success = preprocessor.run()
        
        if not success:
            print("\n❌ 预处理失败，请检查配置和数据")
            
    except KeyboardInterrupt:
        print("\n⏹️  处理被用户中断")
    except Exception as e:
        print(f"\n💥 程序错误：{e}")
        print("\n🔧 排查建议：")
        print("1. 检查文件路径和权限")
        print("2. 验证CSV文件格式和列名")
        print("3. 确保有足够的内存和磁盘空间")
