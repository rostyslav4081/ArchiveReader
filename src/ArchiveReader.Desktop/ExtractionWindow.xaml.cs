using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
namespace ArchiveReader;
public record FieldCandidate(int Index,JsonObject Data,string Label);
public partial class ExtractionWindow:Window
{
    readonly Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker;readonly string page;readonly string? record;string? run;bool busy;
    public string? SavedRecordId{get;private set;}
    static string T(string s)=>Localizer.Text(s);
    public static string Field(string key)=>T(key switch{"person"=>"Основна особа","related1"=>"Пов’язана особа 1","related2"=>"Пов’язана особа 2","date"=>"Дата","place"=>"Місце","house"=>"Номер будинку","age"=>"Вік","text"=>"Транскрипція","notes"=>"Примітки","kind"=>"Тип запису",_=>key});
    public ExtractionWindow(string page,string? record,Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker){this.page=page;this.record=record;this.worker=worker;InitializeComponent();Loaded+=async(_,_)=>{Localizer.Apply(this,Localizer.Language);await Load();if(Environment.GetCommandLineArgs().Contains("--smoke-roadmap")){Candidates.SelectedIndex=0;SmokeCapture.Save(this,"extraction-ui","window.png");Close();}};}
    async Task Load(){if(busy)return;busy=true;try{var result=await worker("field_propose",new(){["page"]=page,["record"]=record},default);run=result["id"]!.ToString();Citation.Text=result["citation"]!.ToString();Candidates.ItemsSource=result["candidates"]!.AsArray().Select((n,i)=>new FieldCandidate(i,n!.AsObject(),Field(n["field"]!.ToString())+": "+n["value"])).ToList();Status.Text=T("Виберіть пропозиції через Ctrl/Shift.");}catch(Exception ex){Status.Text=T("Помилка: ")+T(ex.Message);}finally{busy=false;}}
    async void Reload(object sender,RoutedEventArgs e)=>await Load();
    void ShowEvidence(object sender,SelectionChangedEventArgs e){if(Candidates.SelectedItem is FieldCandidate candidate)Evidence.Text=candidate.Data["evidence"]+"\n\n"+T("Поточне значення")+": "+candidate.Data["existing"];}
    async void Apply(object sender,RoutedEventArgs e){if(busy || run==null)return;busy=true;try{var selected=new JsonArray(Candidates.SelectedItems.Cast<FieldCandidate>().Select(c=>JsonValue.Create(c.Index)).ToArray());var result=await worker("field_apply",new(){["run"]=run,["selected"]=selected,["replace"]=ReplaceExisting.IsChecked==true},default);SavedRecordId=result["id"]!.ToString();DialogResult=true;}catch(Exception ex){Status.Text=T("Помилка: ")+T(ex.Message);}finally{busy=false;}}
}
