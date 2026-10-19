using System.IO;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using Microsoft.Win32;
namespace ArchiveReader;
public partial class OperationsWindow:Window
{
    readonly Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker;readonly JsonObject options;CancellationTokenSource? work;bool busy,closing;
    public string? SelectedPageId{get;private set;}
    static string T(string s)=>Localizer.Text(s);
    Task<JsonNode> Call(string command,JsonObject? args=null)=>worker(command,args,work?.Token ?? default);
    public OperationsWindow(JsonObject options,Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker)
    {this.options=options;this.worker=worker;InitializeComponent();QueueModel.Text=options["model"]?.ToString() ?? "";Loaded+=async(_,_)=>await Run(async()=>{Localizer.Apply(this,Localizer.Language);await LoadBooks();await LoadJobs();await LoadCoverage();if(Environment.GetCommandLineArgs().Contains("--smoke-roadmap")){await Runtime();Tabs.IsEnabled=true;for(int i=0;i<Tabs.Items.Count;i++){Tabs.SelectedIndex=i;SmokeCapture.Save(this,"operations-ui",$"tab-{i}.png");}Close();}});Closing+=(_,e)=>{if(busy && !closing){e.Cancel=true;closing=true;work?.Cancel();}};}
    async Task Run(Func<Task> action)
    {if(busy)return;busy=true;work=new CancellationTokenSource();Tabs.IsEnabled=false;try{await action();}catch(OperationCanceledException){Status.Text=T("Чергу зупинено. Продовжіть її пізніше.");}catch(Exception ex){Status.Text=T("Помилка: ")+T(ex.Message);SmokeCapture.Fail(ex);}finally{Tabs.IsEnabled=true;work.Dispose();work=null;busy=false;if(closing)_ = Dispatcher.BeginInvoke(new Action(Close));}}
    async Task LoadBooks(){Books.ItemsSource=(await Call("batch_books")).AsArray().Select(n=>new GenealogyRow(n!.AsObject(),$"{n["name"]} · {n["done"]}/{n["pages"]}")).ToList();}
    async Task LoadJobs(string? ident=null){Jobs.ItemsSource=(await Call("batch_status")).AsArray().Select(n=>new GenealogyRow(n!.AsObject(),n!["created"]+" · "+n!["id"]!.ToString()[..8])).ToList();Jobs.SelectedItem=Jobs.Items.Cast<GenealogyRow>().FirstOrDefault(r=>r.Data["id"]!.ToString()==ident) ?? Jobs.Items.Cast<GenealogyRow>().FirstOrDefault();}
    string? Job=>(Jobs.SelectedItem as GenealogyRow)?.Data["id"]?.ToString();
    void Report(JsonNode result){var counts=result["counts"]!;QueueReport.Text=string.Join("\n",new[]{("Очікують","queued"),("Обробляються","running"),("Готово","done"),("Помилка","failed"),("Пропущено","skipped")}.Select(pair=>T(pair.Item1)+": "+counts[pair.Item2]))+"\n\n"+string.Join("\n",result["errors"]!.AsArray().Select(n=>$"{n!["name"]} · {n!["num"]!.GetValue<int>()+1}: {n!["error"]}"));}
    async void CreateQueue(object sender,RoutedEventArgs e)=>await Run(async()=>{options["model"]=QueueModel.Text;var docs=new JsonArray(Books.SelectedItems.Cast<GenealogyRow>().Select(r=>JsonValue.Create(r.Data["id"]!.ToString())).ToArray());var result=await Call("batch_create",new(){["documents"]=docs,["options"]=options.DeepClone()});await LoadJobs(result["id"]!.ToString());Report(result);});
    async void SelectJob(object sender,SelectionChangedEventArgs e){if(!busy && Job!=null)await Run(async()=>Report(await Call("batch_status",new(){["job"]=Job})));}
    async void StartQueue(object sender,RoutedEventArgs e)=>await Run(async()=>{var ident=Job;if(ident==null)return;var status=await Call("batch_recover",new(){["job"]=ident,["retry_errors"]=RetryErrors.IsChecked==true});Report(status);while(status["counts"]!["queued"]!.GetValue<int>()>0){work!.Token.ThrowIfCancellationRequested();status=await Call("batch_step",new(){["job"]=ident});Report(status);}await LoadBooks();Status.Text=T("Чергу завершено. Перевірте помилки й результати.");});
    void Stop(object sender,RoutedEventArgs e)=>work?.Cancel();
    void ChooseModel(object sender,RoutedEventArgs e){var dialog=new OpenFileDialog{Filter="Kraken|*.mlmodel;*.safetensors"};if(dialog.ShowDialog()==true)QueueModel.Text=dialog.FileName;}
    async Task LoadCoverage(){Coverage.ItemsSource=(await Call("evaluation_coverage")).AsArray().Select(n=>new GenealogyRow(n!.AsObject(),$"{n["name"]} · {n["languages"]} · {n["script"]} · {n["verified_lines"]}")).ToList();Coverage.SelectedIndex=0;}
    async void RefreshCoverage(object sender,RoutedEventArgs e)=>await Run(LoadCoverage);
    void ShowCoverage(object sender,SelectionChangedEventArgs e){if(Coverage.SelectedItem is GenealogyRow row){var d=row.Data;CoverageReport.Text=string.Join("\n",new[]{("Мови","languages"),("Роки","years"),("Тип письма","script"),("Роль набору","split"),("Перевірені рядки розмітки","verified_lines"),("Перевірені рядки OCR","ocr_verified"),("Позначені пошкодження","damage_regions"),("Сторінки","pages")}.Select(pair=>T(pair.Item1)+": "+d[pair.Item2]));}}
    void OpenCoverage(object sender,RoutedEventArgs e){if(Coverage.SelectedItem is GenealogyRow row){SelectedPageId=row.Data["first_page"]?.ToString();DialogResult=true;}}
    async Task Runtime(){var result=await Call("runtime_check",new(){["model"]=QueueModel.Text});RuntimeReport.Text="Python: "+result["python"]+"\n"+result["executable"]+"\n\n"+string.Join("\n",result["packages"]!.AsObject().Select(pair=>pair.Key+": "+(pair.Value?.ToString() ?? T("Не встановлено"))))+"\n\n"+T("Файл моделі доступний")+": "+T(result["model_exists"]!.GetValue<bool>() ? "Так" : "Ні")+"\nRAM: "+result["profile"]!["ramGB"]+" GB\n"+T("Вільне місце")+": "+result["profile"]!["diskFreeGB"]+" GB";}
    async void CheckRuntime(object sender,RoutedEventArgs e)=>await Run(Runtime);
}
