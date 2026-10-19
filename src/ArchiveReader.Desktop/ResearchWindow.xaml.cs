using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media.Imaging;
namespace ArchiveReader;
public partial class ResearchWindow:Window
{
    readonly string page;readonly Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker;CancellationTokenSource? work;bool busy;
    static string T(string s)=>Localizer.Text(s);
    Task<JsonNode> Call(string command,JsonObject? args=null)=>worker(command,args,work?.Token ?? default);
    public ResearchWindow(string page,Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker,string? query=null){this.page=page;this.worker=worker;InitializeComponent();WordQuery.Text=query ?? "";if(query!=null)Tabs.SelectedIndex=1;Loaded+=async(_,_)=>await Run(async()=>{Localizer.Apply(this,Localizer.Language);await LoadWords();if(Environment.GetCommandLineArgs().Contains("--smoke-roadmap")){await Call("duplicate_index",new(){["limit"]=100});await LoadDuplicates();if(DuplicateRows.SelectedItem is GenealogyRow row)await DuplicateImages(row);Tabs.IsEnabled=true;for(int i=0;i<Tabs.Items.Count;i++){Tabs.SelectedIndex=i;SmokeCapture.Save(this,"research-ui",$"tab-{i}.png");}Close();}});Closing+=(_,_)=>work?.Cancel();}
    async Task Run(Func<Task> action){if(busy)return;busy=true;work=new CancellationTokenSource();Tabs.IsEnabled=false;try{await action();}catch(OperationCanceledException){Status.Text=T("Обробку зупинено. Збережені результати залишилися в бібліотеці.");}catch(Exception ex){Status.Text=T(ex.Message);}finally{Tabs.IsEnabled=true;work.Dispose();work=null;busy=false;}}
    void Stop(object sender,RoutedEventArgs e)=>work?.Cancel();
    void EnlargeScan(object sender,System.Windows.Input.MouseButtonEventArgs e){if(sender is Image image && image.Source!=null)new Window{Owner=this,Title=T("Можливі дублікати"),Width=1000,Height=700,Content=new ScrollViewer{HorizontalScrollBarVisibility=ScrollBarVisibility.Auto,VerticalScrollBarVisibility=ScrollBarVisibility.Auto,Content=new Image{Source=image.Source,Stretch=System.Windows.Media.Stretch.None}}}.ShowDialog();}
    async void IndexScans(object sender,RoutedEventArgs e)=>await Run(async()=>{JsonNode result;do{result=await Call("duplicate_index");Status.Text=T("Залишилося сторінок для індексації")+": "+result["remaining"];work!.Token.ThrowIfCancellationRequested();}while(result["remaining"]!.GetValue<int>()>0);await LoadDuplicates();});
    async Task LoadDuplicates(){DuplicateRows.ItemsSource=(await Call("duplicate_find",new(){["page"]=page})).AsArray().Select(n=>new GenealogyRow(n!.AsObject(),$"{n["name"]} · {n["number"]} · {n["full_similarity"]} / {n["similarity"]} · "+T(n["decision"]?["status"]?.ToString() switch{"confirmed_full"=>"Та сама повна сторінка","related_fragment"=>"Лише спільний фрагмент","rejected"=>"Різні сторінки",_=>"Ще не перевірено"}))).ToList();DuplicateRows.SelectedIndex=0;}
    async void FindDuplicates(object sender,RoutedEventArgs e)=>await Run(LoadDuplicates);
    static BitmapImage Bitmap(string path){var image=new BitmapImage();image.BeginInit();image.CacheOption=BitmapCacheOption.OnLoad;image.UriSource=new Uri(path);image.EndInit();image.Freeze();return image;}
    async Task DuplicateImages(GenealogyRow row){var left=await Call("render",new(){["id"]=row.Data["left"]!.ToString()});var right=await Call("render",new(){["id"]=row.Data["right"]!.ToString()});if(!ReferenceEquals(DuplicateRows.SelectedItem,row))return;LeftImage.Source=Bitmap(left["path"]!.ToString());RightImage.Source=Bitmap(right["path"]!.ToString());DuplicateReason.Text=row.Data["decision"]?["note"]?.ToString() ?? "";}
    async void ShowDuplicate(object sender,SelectionChangedEventArgs e){if(DuplicateRows.SelectedItem is not GenealogyRow row)return;try{await DuplicateImages(row);}catch(Exception ex){Status.Text=T(ex.Message);SmokeCapture.Fail(ex);}}
    async void DecideDuplicate(object sender,RoutedEventArgs e)=>await Run(async()=>{if(DuplicateRows.SelectedItem is not GenealogyRow row)return;await Call("duplicate_decide",new(){["left"]=row.Data[ReverseSource.IsChecked==true ? "right" : "left"]!.ToString(),["right"]=row.Data[ReverseSource.IsChecked==true ? "left" : "right"]!.ToString(),["status"]=(sender as Button)!.Tag.ToString(),["note"]=DuplicateReason.Text});await LoadDuplicates();Status.Text=T("Збережено");});
    async Task LoadWords(){Words.ItemsSource=(await Call("book_dictionary",new(){["page"]=page,["query"]=WordQuery.Text})).AsArray().Select(n=>new GenealogyRow(n!.AsObject(),n["term"]+" — "+n["meaning"]+" · "+n["citation"])).ToList();}
    async void SearchWords(object sender,RoutedEventArgs e)=>await Run(LoadWords);
    async void AddWord(object sender,RoutedEventArgs e)=>await Run(async()=>{await Call("book_dictionary",new(){["page"]=page,["term"]=WordTerm.Text,["meaning"]=WordMeaning.Text,["kind"]=((ComboBoxItem)WordKind.SelectedItem).Tag.ToString(),["verified"]=WordVerified.IsChecked==true});await LoadWords();});
    async void DeleteWord(object sender,RoutedEventArgs e)=>await Run(async()=>{if(Words.SelectedItem is GenealogyRow row){await Call("book_dictionary",new(){["page"]=page,["delete"]=row.Data["id"]!.ToString()});await LoadWords();}});
}
